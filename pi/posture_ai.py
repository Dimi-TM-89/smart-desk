"""
posture_ai.py – AI posture detection (runs on the Raspberry Pi 5).

Grabs about one webcam frame per second, runs the YOLO pose model (NCNN
export) to find ear, shoulder and hip keypoints, calculates the forward lean
of the neck and publishes {"state": "good|bad|none", "angle": ...} on
desk/posture.

Privacy: frames are only processed in memory and never stored or sent.

Status: skeleton.
"""

import config


def main():
    """Entry point: will open the camera, load the model and start the loop."""
    print(f"posture_ai – not implemented yet (model: {config.POSE_MODEL})")


if __name__ == "__main__":
    main()
