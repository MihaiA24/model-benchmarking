package org.springframework.samples.petclinic.owner;

import java.util.HashSet;
import java.util.Set;
import org.springframework.validation.Errors;

public final class PetValidatorBehavior {
	private static final Object PRESENT = new Object();

	private static final class RecordingErrors implements Errors {
		private final Set<String> rejected = new HashSet<>();

		@Override
		public void rejectValue(String field, String code, String defaultMessage) {
			if (!"required".equals(code) || !"required".equals(defaultMessage)) {
				throw new AssertionError("unexpected validation code");
			}
			this.rejected.add(field);
		}
	}

	private static Set<String> validate(String name, boolean isNew, Object type, Object birthDate) {
		RecordingErrors errors = new RecordingErrors();
		new PetValidator().validate(new Pet(name, isNew, type, birthDate), errors);
		return errors.rejected;
	}

	private static boolean acceptance() {
		return validate("   ", false, PRESENT, PRESENT).equals(Set.of("name"));
	}

	private static boolean regression() {
		return validate(null, false, PRESENT, PRESENT).equals(Set.of("name"))
			&& validate("", false, PRESENT, PRESENT).equals(Set.of("name"))
			&& validate("Fido", false, PRESENT, PRESENT).isEmpty()
			&& validate("Fido", true, null, PRESENT).equals(Set.of("type"))
			&& validate("Fido", false, null, PRESENT).isEmpty()
			&& validate("Fido", false, PRESENT, null).equals(Set.of("birthDate"))
			&& new PetValidator().supports(Pet.class);
	}

	private static boolean domain() {
		return validate("\t", false, PRESENT, PRESENT).equals(Set.of("name"))
			&& validate("\n", false, PRESENT, PRESENT).equals(Set.of("name"))
			&& validate(" \t\n ", false, PRESENT, PRESENT).equals(Set.of("name"))
			&& validate("  Fido  ", false, PRESENT, PRESENT).isEmpty();
	}

	public static void main(String[] arguments) {
		if (arguments.length != 1) {
			throw new IllegalArgumentException("one check name is required");
		}
		boolean passed = switch (arguments[0]) {
			case "acceptance" -> acceptance();
			case "regression" -> regression();
			case "domain" -> domain();
			default -> throw new IllegalArgumentException("unknown check");
		};
		if (!passed) {
			System.exit(1);
		}
	}
}
