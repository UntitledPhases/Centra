# Guards

## partition_guard.py
Enforces read/write access by role and partition.
Call `assert_can_write(role, partition)` at the entry of every repository write.
`assert_durable_write_is_promoter(role)` is the shortcut used inside DurableRepository.

## budget_guard.py
Validates budget headers on task creation.
`validate_child_budget(parent, child)` blocks expansion on any dimension.
`check_budget_consumption` is a stub for future accounting (see TODO in file).

## Synthesizer boundary (future)
Synthesizer is a named future role boundary. It has no runtime path in slice-1.
Do not implement synthesizer logic until slice-2 or later.
