package org.springframework.validation;

public interface Validator {
	boolean supports(Class<?> clazz);

	void validate(Object target, Errors errors);
}
