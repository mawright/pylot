from absl import app, flags
import erdos

import pylot.flags
import pylot.component_creator
import pylot.operator_creator
import pylot.utils
from pylot.simulation.utils import get_world, set_asynchronous_mode

FLAGS = flags.FLAGS

flags.DEFINE_list('goal_location', '234, 59, 39', 'Ego-vehicle goal location')

# The location of the center camera relative to the ego-vehicle.
CENTER_CAMERA_LOCATION = pylot.utils.Location(1.5, 0.0, 1.4)


def driver():
    transform = pylot.utils.Transform(CENTER_CAMERA_LOCATION,
                                      pylot.utils.Rotation())

    control_loop_stream = erdos.LoopStream()
    # Create carla operator.
    (can_bus_stream, ground_traffic_lights_stream, ground_obstacles_stream,
     ground_speed_limit_signs_stream, ground_stop_signs_stream,
     vehicle_id_stream, open_drive_stream, global_trajectory_stream
     ) = pylot.operator_creator.add_carla_bridge(control_loop_stream)

    # Add sensors.
    (center_camera_stream,
     rgb_camera_setup) = pylot.operator_creator.add_rgb_camera(
         transform, vehicle_id_stream)
    if pylot.flags.must_add_depth_camera_sensor():
        (depth_camera_stream,
         depth_camera_setup) = pylot.operator_creator.add_depth_camera(
             transform, vehicle_id_stream)
    else:
        depth_camera_stream = None
    if pylot.flags.must_add_segmented_camera_sensor():
        (ground_segmented_stream,
         _) = pylot.operator_creator.add_segmented_camera(
             transform, vehicle_id_stream)
    else:
        ground_segmented_stream = None

    if pylot.flags.must_add_lidar_sensor():
        # Place Lidar sensor in the same location as the center camera.
        (point_cloud_stream, lidar_setup) = pylot.operator_creator.add_lidar(
            transform, vehicle_id_stream)
    else:
        point_cloud_stream = None

    if FLAGS.obstacle_location_finder_sensor == 'lidar':
        depth_stream = point_cloud_stream
    elif FLAGS.obstacle_location_finder_sensor == 'depth_camera':
        depth_stream = depth_camera_stream
    else:
        raise ValueError(
            'Unknown --obstacle_location_finder_sensor value {}'.format(
                FLAGS.obstacle_location_finder_sensor))

    imu_stream = None
    if FLAGS.imu:
        (imu_stream,
         _) = pylot.operator_creator.add_imu(transform, vehicle_id_stream)

    obstacles_stream = \
        pylot.component_creator.add_obstacle_detection(
            center_camera_stream, rgb_camera_setup, can_bus_stream,
            depth_stream, depth_camera_stream, ground_segmented_stream,
            ground_obstacles_stream, ground_speed_limit_signs_stream,
            ground_stop_signs_stream)
    traffic_lights_stream = \
        pylot.component_creator.add_traffic_light_detection(
            transform, vehicle_id_stream, can_bus_stream, depth_stream,
            ground_traffic_lights_stream)

    lane_detection_stream = pylot.component_creator.add_lane_detection(
        center_camera_stream, can_bus_stream)

    obstacles_tracking_stream = pylot.component_creator.add_obstacle_tracking(
        center_camera_stream, rgb_camera_setup, obstacles_stream, depth_stream,
        vehicle_id_stream, can_bus_stream, ground_obstacles_stream)

    segmented_stream = pylot.component_creator.add_segmentation(
        center_camera_stream, ground_segmented_stream)

    depth_stream = pylot.component_creator.add_depth(transform,
                                                     vehicle_id_stream,
                                                     rgb_camera_setup,
                                                     depth_camera_stream)

    if FLAGS.fusion:
        pylot.operator_creator.add_fusion(can_bus_stream, obstacles_stream,
                                          depth_stream,
                                          ground_obstacles_stream)

    prediction_stream = pylot.component_creator.add_prediction(
        obstacles_tracking_stream, vehicle_id_stream, transform,
        can_bus_stream)

    # Add planning operators.
    goal_location = pylot.utils.Location(float(FLAGS.goal_location[0]),
                                         float(FLAGS.goal_location[1]),
                                         float(FLAGS.goal_location[2]))
    waypoints_stream = pylot.component_creator.add_planning(
        goal_location, can_bus_stream, prediction_stream, center_camera_stream,
        obstacles_stream, traffic_lights_stream, open_drive_stream,
        global_trajectory_stream)

    # Add the behaviour planning and control operator.
    control_stream = pylot.component_creator.add_control(
        can_bus_stream, waypoints_stream)
    control_loop_stream.set(control_stream)

    pylot.operator_creator.add_sensor_visualizers(center_camera_stream,
                                                  depth_camera_stream,
                                                  point_cloud_stream,
                                                  ground_segmented_stream,
                                                  imu_stream, can_bus_stream)
    erdos.run()


def main(args):
    # Connect an instance to the simulator to make sure that we can turn the
    # synchronous mode off after the script finishes running.
    client, world = get_world(FLAGS.carla_host, FLAGS.carla_port,
                              FLAGS.carla_timeout)
    if client is None or world is None:
        raise ValueError("There was an issue connecting to the simulator.")

    try:
        driver()
    except KeyboardInterrupt:
        set_asynchronous_mode(world)
    except Exception:
        set_asynchronous_mode(world)
        raise


if __name__ == '__main__':
    app.run(main)
