# Spec 07 — 2-value params as combobox

## TODO item covered

- **#5** — Some pedals that have 2-value params show a tickbox (checkbox)
  instead of a combobox. It should be a combobox with the values.

## Agreed rule

**Every 2-value discrete parameter is displayed as a `QComboBox`** with its
two labels (including On/Off). The `QCheckBox` is no longer used for params
with value information; it remains only as a fallback when labels cannot be
derived.

## Cause

`src/openpodgo/ui/inspector.py` — `ParamRow.__init__` enters the `bool` branch
first and returns early creating a `QCheckBox` (`inspector.py:140-145`):

```python
self._is_bool = isinstance(value, bool) or (spec is not None and spec.is_bool)
if self._is_bool:
    self._kind = "bool"
    self.widget = QCheckBox()
    ...
    return
```

The `enum` branch (combo) comes after and only applies to discrete params with
`len(labels) == n_steps + 1`. 2-value params marked as bool never reach it.

## Required changes

`src/openpodgo/ui/inspector.py` — reorder `ParamRow` logic so that a 2-value
param produces a combo:

- For a 2-value param (bool or length-2 enum), build a
  `QComboBox` with the 2 labels:
  - use the catalog labels (`catalog.control_spec(...).labels`) if they exist;
  - if no labels and the param is boolean, synthesize `["Off", "On"]`.
- Index → value mapping in `on_change`:
  - boolean param → emit `bool(index)` (keep the type `editor.set_param`
    expects for bools);
  - enum → emit `vmin + index` (same as the current `enum` branch).
- `_set_combo_silent` / current value reading must work for the bool case
  (index 0/1 from the boolean or numeric value).
- `QCheckBox` remains as fallback only if no label can be built.

Also review the rest of `ParamRow` (`_kind == "bool"` is used in
`value()`/`set_value`/sync): adapt them to the new bool combo.

## Tests

`tests/` (offline):

- A boolean param (or 2-value enum) produces a `QComboBox` with 2 items,
  not a `QCheckBox`.
- Selecting each item emits the correct value (`False/True` for bool;
  `vmin`/`vmin+1` for enum).
- The initial value selects the correct combo item.

## Pedal verification

1. Open a block whose 2-value param used to show as a tickbox → now a combobox
   with the 2 options should be visible.
2. Change the option in the app → the value must apply on the pedal (same as
   any other param via `set_param`).

## Notes

- Isolated spec: only touches `ui/inspector.py` and its tests. Does not depend
  on specs 05 or 06.
