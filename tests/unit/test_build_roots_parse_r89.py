"""R89 — a function's globals are read with its own build's macros and objects (`generate_uds_source_sections`).

HDPDM01's two builds name the same register differently: APP ``#define SCI0BD REG_SCI0BD.Word``, BOOT
``#define SCI0BD r_SCI0BD.Word``. One name-keyed macro map for both trees resolved BOOT's ``SCI0BD = …`` to APP's
``REG_SCI0BD`` — BOOT functions listed an object BOOT does not have, and the SITS generated from them asked for 6,072
expected values of it (R89, measured).
"""
from __future__ import annotations

from report_gen.uds_generator import generate_uds_source_sections

HDR = "typedef union { unsigned char Byte; } SCISTR;\n"


def _tree(tmp_path):
    app, boot = tmp_path / "app", tmp_path / "boot"
    for root, reg in ((app, "REG_SCI0BD"), (boot, "r_SCI0BD")):
        (root / "Project_Headers").mkdir(parents=True)
        (root / "Sources").mkdir()
        (root / "Project_Headers" / "regs.h").write_text(
            HDR + f"extern volatile SCISTR {reg};\n#define SCI0BD {reg}.Byte\n", encoding="utf-8")
        (root / "Sources" / "regs.c").write_text(
            f'#include "regs.h"\nvolatile SCISTR {reg};\n', encoding="utf-8")
    (app / "Sources" / "a.c").write_text(
        '#include "regs.h"\nvoid app_init(void)\n{\n    SCI0BD = 1U;\n}\n', encoding="utf-8")
    (boot / "Sources" / "b.c").write_text(
        '#include "regs.h"\nvoid boot_init(void)\n{\n    SCI0BD = 2U;\n}\n', encoding="utf-8")
    return app, boot


def _globals(sec, name):
    info = next(i for i in sec["function_details"].values() if i.get("name") == name)
    return " ".join(str(g) for g in (info.get("globals_global") or []) + (info.get("globals_static") or []))


def test_each_build_reads_its_own_register(tmp_path):
    app, boot = _tree(tmp_path)
    sec = generate_uds_source_sections(f"{app};{boot}", preprocess=False)
    boot_g, app_g = _globals(sec, "boot_init"), _globals(sec, "app_init")
    assert "REG_SCI0BD" not in boot_g, boot_g
    assert "r_SCI0BD" in boot_g, boot_g
    assert "REG_SCI0BD" in app_g and "r_SCI0BD" not in app_g, app_g


def test_root_order_does_not_decide_it(tmp_path):
    # the merged map kept whichever definition came last — the answer flipped with the argument order
    app, boot = _tree(tmp_path)
    sec = generate_uds_source_sections(f"{boot};{app}", preprocess=False)
    assert "r_SCI0BD" in _globals(sec, "boot_init") and "REG_SCI0BD" in _globals(sec, "app_init")


def test_one_root_reads_as_before(tmp_path):
    app, _boot = _tree(tmp_path)
    sec = generate_uds_source_sections(str(app), preprocess=False)
    assert "REG_SCI0BD" in _globals(sec, "app_init")


def _twin_tree(tmp_path):
    """Both builds define ``drv_init`` (the HDPDM01 twins: `SCI0_Init`, `EEPROM_SetByte` …) and call it from ``run``."""
    app, boot = _tree(tmp_path)
    for root in (app, boot):
        (root / "Sources" / "drv.c").write_text(
            '#include "regs.h"\nvoid drv_init(void)\n{\n    SCI0BD = 3U;\n}\n'
            'void run(void)\n{\n    drv_init();\n}\n'
            + ('void boot_run(void)\n{\n    drv_init();\n}\n' if root == boot else ''), encoding="utf-8")
    return app, boot


def _globals_at(sec, name, root):
    info = next(i for i in sec["function_details"].values()
                if i.get("name") == name and str(root) in str(i.get("source_path") or i.get("file") or ""))
    return " ".join(str(g) for g in (info.get("globals_global") or []) + (info.get("globals_static") or []))


def test_a_twin_keeps_its_own_globals(tmp_path):
    # the propagation's last step copied the first definition's lists onto every record of the name
    app, boot = _twin_tree(tmp_path)
    sec = generate_uds_source_sections(f"{app};{boot}", preprocess=False)
    boot_g = _globals_at(sec, "drv_init", boot)
    assert "REG_SCI0BD" not in boot_g and "r_SCI0BD" in boot_g, boot_g
    assert "REG_SCI0BD" in _globals_at(sec, "drv_init", app)


def test_a_caller_takes_indirect_globals_from_its_own_builds_callee(tmp_path):
    app, boot = _twin_tree(tmp_path)
    sec = generate_uds_source_sections(f"{app};{boot}", preprocess=False)
    assert "REG_SCI0BD" not in _globals_at(sec, "run", boot)
    # a BOOT-only caller: its callee `drv_init` is BOOT's, not the first definition of the name (APP's)
    boot_run = _globals_at(sec, "boot_run", boot)
    assert "REG_SCI0BD" not in boot_run and "r_SCI0BD" in boot_run, boot_run


def test_a_build_reads_its_registers_from_files_outside_the_document_scope(tmp_path):
    # (리뷰 C1) HDPDM01 BOOT's register header and definitions are verify=X in the component map: the document leaves them
    #   out, the build does not — without them BOOT's `SCI0BD = …` matched nothing and its globals were silently empty
    app, boot = _tree(tmp_path)
    cmap = {"boot/Project_Headers/regs.h": {"verify": "X"}, "boot/Sources/regs.c": {"verify": "X"}}
    sec = generate_uds_source_sections(f"{app};{boot}", preprocess=False, component_map=cmap)
    boot_g = _globals(sec, "boot_init")
    assert "r_SCI0BD" in boot_g and "REG_SCI0BD" not in boot_g, boot_g
    split = sec["globals_scan"]["build_split"]["boot"]
    assert split["context_only_files"] == 2 and split["context_only_macro_rows"] >= 1, split
    assert sec["globals_scan"]["build_split"]["functions"] == {"app": 1, "boot": 1}


def test_the_second_builds_twin_gets_indirect_globals_whatever_the_root_order(tmp_path):
    # (리뷰 W1) only the first definition of a name used to be propagated to — flipping the roots flipped who got it
    for order in ("ab", "ba"):
        app, boot = _twin_tree(tmp_path / order)
        roots = f"{app};{boot}" if order == "ab" else f"{boot};{app}"
        sec = generate_uds_source_sections(roots, preprocess=False)
        for root, reg in ((app, "REG_SCI0BD"), (boot, "r_SCI0BD")):
            got = _globals_at(sec, "run", root)
            assert f"[INDIRECT] {reg}" in got, (order, root.name, got)


def test_two_hop_edges_are_the_callees_own(tmp_path):
    # (리뷰 I6) APP's `drv_init` also calls `leaf`; BOOT's does not — the merged call map gave BOOT callers BOOT's `leaf`
    app, boot = _twin_tree(tmp_path)
    for root, reg in ((app, "REG_SCI0BD"), (boot, "r_SCI0BD")):
        call = "    leaf();\n" if root == app else ""
        (root / "Sources" / "drv.c").write_text(
            '#include "regs.h"\nvoid leaf(void)\n{\n    g_leaf = 1U;\n}\n'
            f'void drv_init(void)\n{{\n    SCI0BD = 3U;\n{call}}}\n'
            'void boot_run(void)\n{\n    drv_init();\n}\n', encoding="utf-8")
        (root / "Sources" / "leafvar.c").write_text("unsigned char g_leaf;\n", encoding="utf-8")
    sec = generate_uds_source_sections(f"{app};{boot}", preprocess=False)
    assert "g_leaf" not in _globals_at(sec, "boot_run", boot), _globals_at(sec, "boot_run", boot)
