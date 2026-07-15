package org.springframework.samples.petclinic.owner;

public class Pet {
	private final Object birthDate;
	private final String name;
	private final boolean newEntity;
	private final Object type;

	public Pet(String name, boolean newEntity, Object type, Object birthDate) {
		this.name = name;
		this.newEntity = newEntity;
		this.type = type;
		this.birthDate = birthDate;
	}

	public Object getBirthDate() {
		return this.birthDate;
	}

	public String getName() {
		return this.name;
	}

	public Object getType() {
		return this.type;
	}

	public boolean isNew() {
		return this.newEntity;
	}
}
