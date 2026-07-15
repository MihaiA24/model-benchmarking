package org.springframework.validation;

public interface Errors {
	void rejectValue(String field, String code, String defaultMessage);
}
