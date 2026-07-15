# Developer Brief

Repair the pet-name validation behavior in this repository.

A new or existing pet name containing only whitespace—spaces, tabs, line breaks, or a mixture—must be rejected with the existing `required` validation error. Null and empty names must remain rejected, nonblank names must remain valid, and the existing type and birth-date validation rules must not change.

Respect the project style and change only `src/main/java/org/springframework/samples/petclinic/owner/PetValidator.java`.
