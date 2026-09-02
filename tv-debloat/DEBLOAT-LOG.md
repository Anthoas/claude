# DEBLOAT-LOG

Every change made to the TCL 43V6C, why, and how to undo it.
`scripts/30-disable-batch.sh` appends a table here automatically after each batch.

- TV: TCL 43V6C
- Address: `192.168.1.43:5555` (override with `export TV_ADDR=...`)
- Rule: `pm disable-user --user 0` only. **`pm uninstall` is never used.**
- Record of disabled packages: [`kapatilanlar.txt`](kapatilanlar.txt)

## Undo everything

```bash
bash scripts/undo.sh --all && adb -s 192.168.1.43:5555 reboot
```

## Change history

_(batches are appended below this line)_
