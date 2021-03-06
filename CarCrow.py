import datetime
from subprocess import check_output
from SimpleCV import *
from crow_config import *


def build_file_list(file_path):
    file_list = []
    for root, folders, files in os.walk(file_path):
        folders.sort()
        files.sort()
        for filename in files:
            if re.search(".(avi|AVI)$", filename) is not None:
                file_list.append(os.path.join(root, filename))
    return file_list


def split_next_video(file_path, output_path):
    check_output("ffmpeg -i \"{0}\" -r 5 \"{1}\{2}%04d.jpg\"".format(file_path, os.path.split(output_path)[0], os.path.split(file_path)[-1].split('.')[0]), shell=True)


def get_bounding_box(image):
    """
    Get a user-defined bounding box chosen from a given image
    :param image: Input image that is displayed
    :return: list containing x, y, w,h of the bounding box
    """

    disp = Display(resolution=image.size())
    image.drawText(text="Drag a bounding box", x=0, y=0, color=Color.HOTPINK, fontsize=20)
    image.save(disp)

    up = None
    down = None
    bb = None

    while disp.isNotDone():

        # Start of bounding box
        if disp.leftButtonDown:
            up = None
            down = disp.leftButtonDownPosition()

        # End of bounding box
        if disp.leftButtonUp:
            up = disp.leftButtonUpPosition()

        # If the box has been defined, draw it
        if up is not None and down is not None:
            bb = disp.pointsToBoundingBox(up, down)
            image.clearLayers()
            image.drawText(text="Drag again or right click to accept", x=0, y=0, color=Color.HOTPINK, fontsize=20)
            image.drawRectangle(bb[0], bb[1], bb[2], bb[3])
            image.save(disp)

        # Exit if the box is accepted
        if disp.rightButtonDown:
            if bb is not None:
                disp.done = True

    disp.quit()

    return bb


def get_traffic_features(before_image,
                         after_image,
                         threshold=20,
                         erodes=3,
                         dilates=40,
                         smooth_aperture=(19, 19),
                         blob_min=30):
    """
    Find movement features between two video frames.
    Differences between the frames are recognised as movement.
    Optimised for vehicle and pedestrian traffic on my shitty webcam.

    :param before_image: first frame; used as 'background'
    :param after_image: movement frame; movement is detected from this frame
    :param threshold: 'noise floor' for motion detection - pixel value must change by this value for valid movement
    :param erodes: number of erosion iterations. High erosions = only large movements are detected
    :param dilates: number of dilation iterations. Fewer dilations = more separate, smaller movements counted
    :param smooth_aperture: Aperture size for combining movement blobs
    :param blob_min: Cutoff for motion size
    :return: feature set for detected movement
    """

    # Smooth the frames to remove noise, then subtract to find movement
    detect_image = before_image.smooth() - after_image.smooth()

    # Extract features from the differential by processing the crap out of it
    # Everything needs to happen in order: Blur, Threshold, Erode, Dialate, Blur, Blob. BTEDBBl!!
    detect_image = detect_image.threshold(threshold)  # Remove tiny differences in movement
    detect_image = detect_image.erode(iterations=erodes)  # Cut small movements out
    detect_image = detect_image.dilate(
        iterations=dilates)  # Blow up the remaining blobs to combine into large movements
    detect_image = detect_image.smooth(aperature=smooth_aperture)  # Blur blobs together like a lava lamp

    return detect_image.findBlobs(minsize=blob_min)  # Detect and sort out blobs


def find_traffic(images, timestamp=datetime.datetime.now(), output_path="", detection_area=(0,0,0,0), output_images=True, output_log=True):
    last_image = Image(images[0])
    last_detections = 0
    total_detections = 0
    last_detection_time = timestamp

    detect_xmin = detection_area[0]
    detect_xmax = detect_xmin + detection_area[2]
    detect_ymin = detection_area[1]
    detect_ymax = detect_ymin + detection_area[3]

    for image in images:
        num_detections = 0

        next_image = Image(image)
        features = get_traffic_features(last_image, next_image, threshold=THRESHOLD_MINIMUM,
                                        erodes=ERODE_ITERATIONS,
                                        dilates=DILATE_ITERATIONS,
                                        smooth_aperture=SMOOTHING_APERTURE,
                                        blob_min=MIN_BLOB_SIZE)

        # Draw bounding rectangle for detection area
        next_image.drawRectangle(detection_area[0], detection_area[1], detection_area[2], detection_area[3], color=Color.VIOLET, width=2)

        if features is not None:

            for blob in features:

                detection_colour = Color.RED

                # Paint the blob box green if in the detection area
                if detect_xmin <= blob.x <= detect_xmax:
                    if detect_ymin <= blob.y <= detect_ymax:
                        detection_colour = Color.FORESTGREEN
                        num_detections += 1

                # Draw the blob box and centroid
                next_image.drawRectangle(blob.x - (blob.width() / 2), blob.y - (blob.height() / 2), blob.width(),
                                         blob.height(), color=detection_colour, width=3)
                next_image.drawCircle(ctr=blob.centroid(), rad=10, color=Color.LEGO_ORANGE, thickness=5)

        # Only count the detection if there are more in the zone compared to last frame
        if num_detections > last_detections:
            time_since_last_detection = timestamp - last_detection_time
            time_since_last_detection = time_since_last_detection.total_seconds()

            # Cooldown to block repeat detections (centroid tends to bounce)
            if time_since_last_detection > DETECTION_COOLDOWN:
                total_detections += 1
                last_detection_time = timestamp

                # Save motion image
                if output_images:
                    next_image.save("{}motion {}.jpg".format(output_path, timestamp.strftime('%Y-%m-%d %H.%M.%S')))

                # Log the event
                if output_log:
                    file = open("{0}{1}".format(OUTPUT_FOLDER, LOG_FILENAME), mode='a')
                    file.write("{}\n".format(timestamp.strftime('%H:%M:%S')))
                    file.close()

                print "Detection at: {}".format(timestamp.strftime('%H:%M:%S'))

        timestamp += datetime.timedelta(milliseconds=200)
        last_image = next_image
        last_detections = num_detections


if __name__ == '__main__':

    # Find video list and print to confirm numbers/order
    videos = build_file_list(VIDEO_PATH)
    for video in videos:
        print video
    print "{} videos found".format(len(videos))

    start_time = datetime.datetime.strptime(START_TIME, "%Y-%m-%d %H:%M:%S")

    first_video = True
    bounding_box = None

    for video in videos:
        split_next_video(video, TEMP_FOLDER)

        # Load up image set
        image_set = list()
        directory = os.path.join(TEMP_FOLDER, EXTENSION)
        image_set = glob.glob(directory)

        if first_video:
            sample_image = Image(image_set[len(image_set)/2])
            bounding_box = get_bounding_box(sample_image)
            print bounding_box
            first_video = False

        find_traffic(image_set, timestamp=start_time, output_path=OUTPUT_FOLDER, detection_area=bounding_box)

        # Update starting time
        start_time += datetime.timedelta(seconds=(len(image_set) / FRAME_RATE) - 1)

        # Clear folder
        for f in image_set:
            os.remove(f)






