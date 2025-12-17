"""Table structure detection from images using OCR and computer vision.

This module provides hybrid table extraction:
1. Auto-rotation detection using OCR confidence scores
2. Table structure detection using horizontal line detection
3. The detected structure guides LLM extraction of handwritten content
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import pytesseract

logger = logging.getLogger(__name__)


def detect_table_structure(image_path: Path) -> dict:
    """
    Detect table structure from an AWS Wine Evaluation Chart image.

    Uses computer vision to:
    1. Auto-detect and correct image rotation
    2. Detect horizontal table lines to identify row boundaries
    3. Return structure information to guide LLM extraction

    Args:
        image_path: Path to the image file

    Returns:
        dict with:
            - rotation_angle: Best rotation angle applied (0, 90, 180, or 270)
            - num_rows: Number of table rows detected
            - row_boundaries: List of (top_y, bottom_y, height) tuples for each row
            - corrected_image_path: Path to rotation-corrected image (if saved)
    """
    # Step 1: Detect best rotation
    logger.info(f"Detecting best rotation for {image_path}")
    best_angle = detect_best_rotation(image_path)
    logger.info(f"Best rotation: {best_angle}°")

    # Step 2: Load and rotate image
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    rotated_img = rotate_image(img, best_angle)

    # Step 3: Detect horizontal lines (table row boundaries)
    row_boundaries = detect_horizontal_lines(rotated_img)
    logger.info(f"Detected {len(row_boundaries)} table rows")

    # Step 4: Detect vertical lines (table column boundaries)
    column_boundaries = detect_vertical_lines(rotated_img)
    logger.info(f"Detected {len(column_boundaries)} table columns")

    # Step 5: Extract OCR text from each column to help LLM understand layout
    column_text = extract_column_text(rotated_img, column_boundaries, row_boundaries)

    return {
        'rotation_angle': best_angle,
        'num_rows': len(row_boundaries),
        'row_boundaries': row_boundaries,
        'num_columns': len(column_boundaries),
        'column_boundaries': column_boundaries,
        'column_text': column_text,  # OCR-extracted text organized by column and row
        'rotated_image': rotated_img  # Return rotated image for LLM
    }


def detect_best_rotation(image_path: Path) -> int:
    """
    Detect the best rotation for OCR by trying all 4 orientations.

    Scores each rotation based on:
    - Number of confident text detections (conf > 30)
    - Average confidence of detections

    Args:
        image_path: Path to the image file

    Returns:
        rotation angle (0, 90, 180, or 270 degrees)
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    results = {}

    for angle in [0, 90, 180, 270]:
        # Rotate image
        rotated = rotate_image(img, angle)

        # Convert to grayscale
        gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)

        # Run OCR
        try:
            ocr_data = pytesseract.image_to_data(
                gray,
                output_type=pytesseract.Output.DICT
            )
        except Exception as e:
            logger.warning(f"OCR failed for angle {angle}: {e}")
            results[angle] = {'count': 0, 'avg_conf': 0, 'score': 0}
            continue

        # Count confident text detections
        confident_texts = 0
        total_confidence = 0
        for i in range(len(ocr_data['text'])):
            text = ocr_data['text'][i].strip()
            conf = int(ocr_data['conf'][i])
            if text and conf > 30:  # Only count reasonably confident detections
                confident_texts += 1
                total_confidence += conf

        avg_confidence = total_confidence / max(confident_texts, 1)

        results[angle] = {
            'count': confident_texts,
            'avg_conf': avg_confidence,
            'score': confident_texts * avg_confidence  # Combined score
        }

        logger.debug(
            f"Rotation {angle}°: {confident_texts} confident texts, "
            f"avg conf {avg_confidence:.1f}, score {results[angle]['score']:.1f}"
        )

    # Pick the rotation with the highest score
    best_angle = max(results.keys(), key=lambda k: results[k]['score'])
    logger.info(
        f"Best rotation: {best_angle}° "
        f"(score: {results[best_angle]['score']:.1f})"
    )

    return best_angle


def rotate_image(img: np.ndarray, angle: int) -> np.ndarray:
    """
    Rotate image by specified angle.

    Args:
        img: Input image array
        angle: Rotation angle (0, 90, 180, or 270)

    Returns:
        Rotated image array
    """
    if angle == 0:
        return img.copy()
    elif angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    elif angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    else:
        raise ValueError(f"Invalid angle: {angle}. Must be 0, 90, 180, or 270.")


def detect_horizontal_lines(img: np.ndarray) -> list[dict]:
    """
    Detect horizontal table lines to identify row boundaries.

    Uses edge detection and Hough Line Transform to find horizontal lines,
    which indicate table row boundaries in structured forms.

    Args:
        img: Input image array

    Returns:
        List of dicts with row boundary information:
            - top: Y-coordinate of top boundary
            - bottom: Y-coordinate of bottom boundary
            - height: Height of the row in pixels
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Use edge detection to find lines
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    # Detect horizontal lines using HoughLinesP
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi/180,
        threshold=100,
        minLineLength=200,
        maxLineGap=10
    )

    horizontal_lines = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            # Only keep horizontal lines (y1 ≈ y2)
            if abs(y2 - y1) < 10:  # Nearly horizontal
                horizontal_lines.append((y1 + y2) // 2)  # Store y-coordinate

    # Sort and deduplicate (merge lines within 20 pixels)
    horizontal_lines = sorted(set(horizontal_lines))
    merged_lines = []
    for line_y in horizontal_lines:
        if not merged_lines or line_y - merged_lines[-1] > 20:
            merged_lines.append(line_y)

    logger.debug(
        f"Detected {len(merged_lines)} horizontal lines at "
        f"y-coordinates: {merged_lines}"
    )

    # Identify rows based on consecutive lines
    rows = []
    for i in range(len(merged_lines) - 1):
        top_y = merged_lines[i]
        bottom_y = merged_lines[i + 1]
        rows.append({
            'top': top_y,
            'bottom': bottom_y,
            'height': bottom_y - top_y
        })

    logger.info(f"Identified {len(rows)} table rows from horizontal lines")
    for i, row in enumerate(rows):
        logger.debug(
            f"  Row {i}: y={row['top']}-{row['bottom']}, "
            f"height={row['height']}px"
        )

    return rows


def detect_vertical_lines(img: np.ndarray) -> list[dict]:
    """
    Detect vertical table lines to identify column boundaries.

    Uses edge detection and Hough Line Transform to find vertical lines,
    which indicate table column boundaries in structured forms.

    Args:
        img: Input image array

    Returns:
        List of dicts with column boundary information:
            - left: X-coordinate of left boundary
            - right: X-coordinate of right boundary
            - width: Width of the column in pixels
            - label: Column label (Wine, Price, Appearance, Aroma, etc.)
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Use edge detection to find lines
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    # Detect vertical lines using HoughLinesP
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi/180,
        threshold=100,
        minLineLength=200,
        maxLineGap=10
    )

    vertical_lines = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            # Only keep vertical lines (x1 ≈ x2)
            if abs(x2 - x1) < 10:  # Nearly vertical
                vertical_lines.append((x1 + x2) // 2)  # Store x-coordinate

    # Sort and deduplicate (merge lines within 20 pixels)
    vertical_lines = sorted(set(vertical_lines))
    merged_lines = []
    for line_x in vertical_lines:
        if not merged_lines or line_x - merged_lines[-1] > 20:
            merged_lines.append(line_x)

    logger.debug(
        f"Detected {len(merged_lines)} vertical lines at "
        f"x-coordinates: {merged_lines}"
    )

    # Identify columns based on consecutive lines
    columns = []
    # Column labels for AWS Wine Evaluation Chart
    column_labels = [
        "Wine", "Price", "Appearance", "Aroma/Bouquet",
        "Taste/Texture", "Aftertaste", "Overall Impression", "Total Score"
    ]

    for i in range(len(merged_lines) - 1):
        left_x = merged_lines[i]
        right_x = merged_lines[i + 1]
        label = column_labels[i] if i < len(column_labels) else f"Column {i}"
        columns.append({
            'left': left_x,
            'right': right_x,
            'width': right_x - left_x,
            'label': label
        })

    logger.info(f"Identified {len(columns)} table columns from vertical lines")
    for i, col in enumerate(columns):
        logger.debug(
            f"  Column {i} ({col['label']}): x={col['left']}-{col['right']}, "
            f"width={col['width']}px"
        )

    return columns


def extract_column_text(img: np.ndarray, column_boundaries: list[dict], row_boundaries: list[dict]) -> dict:
    """
    Extract OCR text from each column region to help LLM understand spatial layout.

    For each column, extract all text found in that column and organize by row.
    This gives the LLM concrete examples of what text appears where.

    Args:
        img: Input image array
        column_boundaries: List of column boundary dicts
        row_boundaries: List of row boundary dicts

    Returns:
        Dict mapping column labels to lists of text found in each row of that column
    """
    import pytesseract

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Run OCR on full image to get all text with positions
    try:
        ocr_data = pytesseract.image_to_data(
            gray,
            output_type=pytesseract.Output.DICT
        )
    except Exception as e:
        logger.warning(f"OCR failed for column text extraction: {e}")
        return {}

    # Organize text by column and row
    column_text = {col['label']: [[] for _ in row_boundaries] for col in column_boundaries}

    for i in range(len(ocr_data['text'])):
        text = ocr_data['text'][i].strip()
        conf = int(ocr_data['conf'][i])

        if not text or conf < 30:  # Skip low-confidence text
            continue

        x_center = ocr_data['left'][i] + ocr_data['width'][i] // 2
        y_center = ocr_data['top'][i] + ocr_data['height'][i] // 2

        # Find which column this text belongs to
        for col in column_boundaries:
            if col['left'] <= x_center <= col['right']:
                # Find which row this text belongs to
                for row_idx, row in enumerate(row_boundaries):
                    if row['top'] <= y_center <= row['bottom']:
                        column_text[col['label']][row_idx].append(text)
                        break
                break

    # Convert lists to space-separated strings
    for col_label in column_text:
        column_text[col_label] = [' '.join(words) for words in column_text[col_label]]

    logger.debug("Extracted column text:")
    for col_label, rows in column_text.items():
        for row_idx, text in enumerate(rows):
            if text:
                logger.debug(f"  {col_label}, Row {row_idx+1}: '{text}'")

    return column_text
