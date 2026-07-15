package org.springframework.util;

public final class StringUtils {
	private StringUtils() {
	}

	public static boolean hasLength(String value) {
		return value != null && !value.isEmpty();
	}

	public static boolean hasText(String value) {
		if (!hasLength(value)) {
			return false;
		}
		for (int index = 0; index < value.length(); index++) {
			if (!Character.isWhitespace(value.charAt(index))) {
				return true;
			}
		}
		return false;
	}
}
