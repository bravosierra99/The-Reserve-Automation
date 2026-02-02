"""Robust parsing utilities for LLM responses.

This module provides utilities to safely parse LLM responses that may contain:
- Malformed JSON
- Fields with incorrect types
- Text that exceeds field length limits
- Missing required fields
- Invalid enum values

The philosophy is: Never crash the application due to bad LLM output.
Instead, log warnings and use sensible defaults.
"""

import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Type, TypeVar, Union
from loguru import logger
from pydantic import BaseModel, ValidationError

T = TypeVar('T', bound=BaseModel)


class LLMResponseParser:
    """Robust parser for LLM responses."""

    @staticmethod
    def safe_parse_json(response_text: str, context: str = "LLM response") -> Optional[Dict[str, Any]]:
        """
        Safely extract and parse JSON from LLM response.

        Handles:
        - Markdown code blocks (```json...```)
        - Extra text before/after JSON
        - Malformed JSON

        Args:
            response_text: Raw LLM response text
            context: Description for logging (e.g., "image extraction", "tasting card")

        Returns:
            Parsed dict or None if parsing fails
        """
        if not response_text or not response_text.strip():
            logger.warning(f"[{context}] Empty response from LLM")
            return None

        try:
            # Step 1: Remove markdown code blocks if present
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                # Remove first line (```json) and last line (```)
                if len(lines) > 2:
                    cleaned = "\n".join(lines[1:-1])
                    logger.debug(f"[{context}] Removed markdown code blocks")

            # Step 2: Find JSON boundaries (try array first, then object)
            array_start = cleaned.find("[")
            array_end = cleaned.rfind("]") + 1
            object_start = cleaned.find("{")
            object_end = cleaned.rfind("}") + 1

            # Prefer array if both are present and array comes first
            if array_start >= 0 and array_end > array_start:
                if object_start < 0 or array_start < object_start:
                    json_start = array_start
                    json_end = array_end
                else:
                    json_start = object_start
                    json_end = object_end
            elif object_start >= 0 and object_end > object_start:
                json_start = object_start
                json_end = object_end
            else:
                json_start = -1
                json_end = -1

            if json_start < 0 or json_end <= json_start:
                logger.error(f"[{context}] No JSON found in response (no {{ or [ detected)")
                logger.debug(f"[{context}] Response preview: {response_text[:200]}")
                return None

            json_str = cleaned[json_start:json_end]

            # Step 3: Parse JSON
            data = json.loads(json_str)
            logger.debug(f"[{context}] Successfully parsed JSON")
            return data

        except json.JSONDecodeError as e:
            logger.error(f"[{context}] JSON decode error: {e}")
            logger.debug(f"[{context}] Failed JSON: {response_text[:500]}")
            return None
        except Exception as e:
            logger.error(f"[{context}] Unexpected error parsing JSON: {e}")
            return None

    @staticmethod
    def sanitize_string(
        value: Any,
        max_length: Optional[int] = None,
        field_name: str = "field",
        default: str = ""
    ) -> str:
        """
        Safely convert value to string and truncate if needed.

        Args:
            value: Value to convert
            max_length: Maximum length (truncates if exceeded)
            field_name: Field name for logging
            default: Default value if conversion fails

        Returns:
            Sanitized string
        """
        if value is None:
            return default

        try:
            str_value = str(value).strip()

            if max_length and len(str_value) > max_length:
                logger.warning(
                    f"Field '{field_name}' too long ({len(str_value)} chars), "
                    f"truncating to {max_length} chars"
                )
                str_value = str_value[:max_length].rstrip()

            return str_value

        except Exception as e:
            logger.error(f"Failed to convert '{field_name}' to string: {e}")
            return default

    @staticmethod
    def sanitize_int(
        value: Any,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        field_name: str = "field",
        default: Optional[int] = None
    ) -> Optional[int]:
        """
        Safely convert value to integer with range validation.

        Args:
            value: Value to convert
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            field_name: Field name for logging
            default: Default value if conversion fails

        Returns:
            Sanitized integer or default
        """
        if value is None:
            return default

        try:
            # Handle string numbers
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return default
                # Extract first number from string
                match = re.search(r'-?\d+', value)
                if match:
                    value = match.group(0)
                else:
                    logger.warning(f"No integer found in '{field_name}': {value}")
                    return default

            int_value = int(float(value))  # Handle "123.0" strings

            # Validate range
            if min_value is not None and int_value < min_value:
                logger.warning(
                    f"Field '{field_name}' value {int_value} below minimum {min_value}, "
                    f"using default"
                )
                return default

            if max_value is not None and int_value > max_value:
                logger.warning(
                    f"Field '{field_name}' value {int_value} above maximum {max_value}, "
                    f"using default"
                )
                return default

            return int_value

        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to convert '{field_name}' to int: {value} ({e})")
            return default

    @staticmethod
    def sanitize_float(
        value: Any,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        field_name: str = "field",
        default: Optional[float] = None
    ) -> Optional[float]:
        """
        Safely convert value to float with range validation.

        Args:
            value: Value to convert
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            field_name: Field name for logging
            default: Default value if conversion fails

        Returns:
            Sanitized float or default
        """
        if value is None:
            return default

        try:
            # Handle string numbers
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return default
                # Extract first number from string (supports decimals)
                match = re.search(r'-?\d+\.?\d*', value)
                if match:
                    value = match.group(0)
                else:
                    logger.warning(f"No number found in '{field_name}': {value}")
                    return default

            float_value = float(value)

            # Validate range
            if min_value is not None and float_value < min_value:
                logger.warning(
                    f"Field '{field_name}' value {float_value} below minimum {min_value}, "
                    f"using default"
                )
                return default

            if max_value is not None and float_value > max_value:
                logger.warning(
                    f"Field '{field_name}' value {float_value} above maximum {max_value}, "
                    f"using default"
                )
                return default

            return float_value

        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to convert '{field_name}' to float: {value} ({e})")
            return default

    @staticmethod
    def sanitize_enum(
        value: Any,
        valid_values: List[str],
        field_name: str = "field",
        default: Optional[str] = None,
        case_sensitive: bool = False
    ) -> Optional[str]:
        """
        Safely validate enum value against allowed values.

        Args:
            value: Value to validate
            valid_values: List of allowed values
            field_name: Field name for logging
            default: Default value if validation fails (should be in valid_values)
            case_sensitive: Whether to do case-sensitive matching

        Returns:
            Valid enum value or default
        """
        if value is None:
            return default

        try:
            str_value = str(value).strip()

            if not case_sensitive:
                str_value = str_value.lower()
                valid_values_lower = [v.lower() for v in valid_values]

                if str_value in valid_values_lower:
                    # Return original casing from valid_values
                    idx = valid_values_lower.index(str_value)
                    return valid_values[idx]
            else:
                if str_value in valid_values:
                    return str_value

            logger.warning(
                f"Field '{field_name}' has invalid value '{value}', "
                f"expected one of {valid_values}, using default '{default}'"
            )
            return default

        except Exception as e:
            logger.error(f"Failed to validate '{field_name}': {e}")
            return default

    @staticmethod
    def sanitize_date(
        value: Any,
        field_name: str = "field",
        default: Optional[date] = None
    ) -> Optional[date]:
        """
        Safely convert value to date object.

        Supports:
        - ISO format (YYYY-MM-DD)
        - Date objects
        - Datetime objects

        Args:
            value: Value to convert
            field_name: Field name for logging
            default: Default value if conversion fails

        Returns:
            Date object or default
        """
        if value is None:
            return default

        try:
            # Already a date
            if isinstance(value, date):
                return value

            # Datetime to date
            if isinstance(value, datetime):
                return value.date()

            # String parsing
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return default

                # Try ISO format
                try:
                    return date.fromisoformat(value)
                except ValueError:
                    pass

                # Try common formats
                for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                    try:
                        return datetime.strptime(value, fmt).date()
                    except ValueError:
                        continue

            logger.warning(f"Failed to parse date from '{field_name}': {value}")
            return default

        except Exception as e:
            logger.error(f"Error parsing date '{field_name}': {e}")
            return default

    @staticmethod
    def sanitize_list(
        value: Any,
        field_name: str = "field",
        default: Optional[List] = None
    ) -> List:
        """
        Safely convert value to list.

        Args:
            value: Value to convert
            field_name: Field name for logging
            default: Default value if conversion fails

        Returns:
            List or default (or empty list if default is None)
        """
        if default is None:
            default = []

        if value is None:
            return default

        try:
            # Already a list
            if isinstance(value, list):
                return value

            # Convert single value to list
            if isinstance(value, (str, int, float)):
                return [value]

            # Try to iterate
            try:
                return list(value)
            except TypeError:
                logger.warning(f"Cannot convert '{field_name}' to list: {type(value)}")
                return default

        except Exception as e:
            logger.error(f"Error converting '{field_name}' to list: {e}")
            return default

    @staticmethod
    def safe_model_create(
        model_class: Type[T],
        data: Dict[str, Any],
        context: str = "model",
        required_defaults: Optional[Dict[str, Any]] = None
    ) -> Optional[T]:
        """
        Safely create a Pydantic model from dict, with fallback for validation errors.

        Args:
            model_class: Pydantic model class to instantiate
            data: Dictionary with field values
            context: Description for logging
            required_defaults: Default values for required fields if missing

        Returns:
            Model instance or None if creation fails
        """
        try:
            # Apply required defaults for missing or empty fields
            if required_defaults:
                for field, default_value in required_defaults.items():
                    # Check for missing, None, or empty string (but not other falsy values like 0 or False)
                    value = data.get(field)
                    if field not in data or value is None or (isinstance(value, str) and value == ""):
                        data[field] = default_value
                        logger.info(f"[{context}] Using default for '{field}': {default_value}")

            # Try to create model
            instance = model_class(**data)
            return instance

        except ValidationError as e:
            logger.error(f"[{context}] Pydantic validation error creating {model_class.__name__}:")

            # Log each error
            for error in e.errors():
                field = ".".join(str(f) for f in error["loc"])
                msg = error["msg"]
                value = data.get(error["loc"][0]) if error["loc"] else None
                logger.error(f"  - Field '{field}': {msg} (value: {value})")

            # Try again with sanitized data for common issues
            sanitized_data = data.copy()
            for error in e.errors():
                if error["loc"]:
                    field_name = error["loc"][0]
                    error_type = error["type"]

                    # String too long
                    if "string_too_long" in error_type or "max_length" in error_type:
                        max_len = error.get("ctx", {}).get("max_length", 100)
                        sanitized_data[field_name] = LLMResponseParser.sanitize_string(
                            data.get(field_name),
                            max_length=max_len,
                            field_name=field_name
                        )
                        logger.info(f"[{context}] Truncated '{field_name}' to {max_len} chars")

                    # String too short (empty) - apply defaults
                    elif "string_too_short" in error_type:
                        if required_defaults and field_name in required_defaults:
                            sanitized_data[field_name] = required_defaults[field_name]
                            logger.info(f"[{context}] Applied default for empty '{field_name}': {required_defaults[field_name]}")
                        else:
                            # Remove field to trigger model's own default
                            if field_name in sanitized_data:
                                del sanitized_data[field_name]
                                logger.info(f"[{context}] Removed empty field '{field_name}'")

                    # Invalid type - try to convert
                    elif "type_error" in error_type:
                        # Remove the field and let model use default
                        if field_name in sanitized_data:
                            logger.info(f"[{context}] Removing invalid field '{field_name}'")
                            del sanitized_data[field_name]

            # Retry with sanitized data
            try:
                instance = model_class(**sanitized_data)
                logger.warning(f"[{context}] Created {model_class.__name__} with sanitized data")
                return instance
            except ValidationError as e2:
                logger.error(f"[{context}] Still failed after sanitization: {e2}")
                return None

        except Exception as e:
            logger.error(f"[{context}] Unexpected error creating {model_class.__name__}: {e}")
            return None
