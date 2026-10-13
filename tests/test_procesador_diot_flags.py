"""Tests de los flags por comprobante (interruptor DIOT + deducibilidad).

Cubre la migración 009 (columnas + defaults + upgrade desde 008), el método
`actualizar_flags_cfdi`, el filtro «Estado DIOT» en listar/stats, las columnas
nuevas del export y el endpoint `PATCH /procesador/cfdi/{uuid}`.
"""

import shutil

import pytest

from sat_descarga.procesador import parse_cfdi
from sat_descarga.procesador import db as db_mod
from sat_descarga.procesador.exportar import to_csv
from sat_descarga.procesador.reportes_cfdi import stats_generales
from sat_descarga.procesador.validaciones import validar_y_anotar

from .test_procesador_cfdi import _cfdi_ingreso_xml, _cfdi_pago_xml

RFC_A = "AAA010101AAA"  # emisor de los fixtures
RFC_B = "BBB020202BBB"  # receptor de los fixtures

UUID_INGRESO = "AAAAAAAA-1111-2222-3333-444444444444"  # default del fixture
UUID_PAGO = "PPPPPPPP-1111-2222-3333-444444444444"


@pytest.fixture()
def db(tmp_path):
    # abrir_db (no ProcesadorDB directo): siembra el singleton para que los
    # endpoints del API usen ESTA DB temporal y no la real del usuario.
    db_mod.resetear_singleton_para_tests()
    inst = db_mod.abrir_db(tmp_path / "test.db")
    yield inst
    db_mod.resetear_singleton_para_tests()


def _cargar(db, xml: bytes, mi_rfc: str) -> None:
    db.agregar([validar_y_anotar(parse_cfdi(xml))], mi_rfc=mi_rfc)


# ---------------------------------------------------------------------------
# Migración 009
# ---------------------------------------------------------------------------


def test_migracion_009_columnas_y_defaults(db):
    with db.cursor() as cur:
        cur.execute("PRAGMA table_info(cfdis)")
        columnas = {r[1] for r in cur.fetchall()}
    assert {"incluir_diot", "deducible"} <= columnas

    # Fila nueva: pasa a la DIOT por default y sin clasificar deducibilidad.
    _cargar(db, _cfdi_ingreso_xml(), mi_rfc=RFC_B)
    (item,) = db.listar({"mi_rfc": RFC_B})["items"]
    assert item["incluir_diot"] is True
    assert item["deducible"] is None
    assert item["elegible_diot"] is True  # recibido de tipo I


def test_migracion_008_a_009_preserva_filas(tmp_path):
    """Upgrade real: una DB en v008 poblada sube a v009 sin perder datos y las
    filas existentes quedan con incluir_diot = 1 (pasan a la DIOT)."""
    ocultas = [
        (mig, tmp_path / f"{mig.name}.bak")
        for mig in sorted(db_mod.MIGRATIONS_DIR.glob("*.sql"))
        if int(mig.name[:3]) > 8
    ]
    db_path = tmp_path / "procesador.db"

    db_mod.resetear_singleton_para_tests()
    try:
        # 1) DB "vieja" en v008: nada posterior en el directorio de migraciones.
        for mig, fuera in ocultas:
            shutil.move(str(mig), str(fuera))
        vieja = db_mod.ProcesadorDB(db_path)
        try:
            with vieja.cursor() as c:
                c.execute("SELECT value FROM _meta WHERE key='schema_version'")
                assert c.fetchone()[0] == "8"
                # INSERT como lo haría la app de entonces (sin columnas posteriores).
                c.execute(
                    "INSERT INTO cfdis (uuid, mi_rfc, tipo, fecha, emisor_rfc, "
                    "receptor_rfc, direccion) VALUES ('LEGACY-1', ?, 'I', "
                    "'2026-05-15T10:00:00', 'AAA010101AAA', ?, 'R')",
                    (RFC_B, RFC_B),
                )
                c.connection.commit()
        finally:
            vieja.close()
    finally:
        # Restaurar las migraciones pase lo que pase (crítico para la suite).
        for mig, fuera in ocultas:
            if fuera.exists():
                shutil.move(str(fuera), str(mig))
        db_mod.resetear_singleton_para_tests()

    # 2) La app nueva reabre la misma DB → aplica la 009 (y las posteriores).
    nueva = db_mod.ProcesadorDB(db_path)
    try:
        with nueva.cursor() as c:
            c.execute("SELECT value FROM _meta WHERE key='schema_version'")
            assert c.fetchone()[0] == str(db_mod.schema_version_actual())
        (item,) = nueva.listar({"mi_rfc": RFC_B})["items"]
        assert item["incluir_diot"] is True and item["deducible"] is None
    finally:
        nueva.close()
        db_mod.resetear_singleton_para_tests()


# ---------------------------------------------------------------------------
# actualizar_flags_cfdi
# ---------------------------------------------------------------------------


def test_actualizar_flags_toggle_y_deducible(db):
    _cargar(db, _cfdi_ingreso_xml(), mi_rfc=RFC_B)

    item = db.actualizar_flags_cfdi(UUID_INGRESO, RFC_B, {"incluir_diot": 0})
    assert item["incluir_diot"] is False
    item = db.actualizar_flags_cfdi(UUID_INGRESO, RFC_B, {"incluir_diot": 1})
    assert item["incluir_diot"] is True

    item = db.actualizar_flags_cfdi(UUID_INGRESO, RFC_B, {"deducible": "No deducible"})
    assert item["deducible"] == "No deducible"
    item = db.actualizar_flags_cfdi(UUID_INGRESO, RFC_B, {"deducible": None})
    assert item["deducible"] is None

    with pytest.raises(ValueError):
        db.actualizar_flags_cfdi(UUID_INGRESO, RFC_B, {"deducible": "Quizá"})
    with pytest.raises(ValueError):
        db.actualizar_flags_cfdi(UUID_INGRESO, RFC_B, {})


def test_actualizar_flags_rechaza_diot_en_no_elegibles(db):
    # Emitida (la empresa es la emisora) y complemento de pago: no elegibles.
    _cargar(db, _cfdi_ingreso_xml(), mi_rfc=RFC_A)
    _cargar(db, _cfdi_pago_xml(), mi_rfc=RFC_B)

    for uuid, dueno in ((UUID_INGRESO, RFC_A), (UUID_PAGO, RFC_B)):
        with pytest.raises(ValueError):
            db.actualizar_flags_cfdi(uuid, dueno, {"incluir_diot": 0})
        # La deducibilidad sí se puede clasificar en cualquier fila.
        item = db.actualizar_flags_cfdi(uuid, dueno, {"deducible": "Deducible"})
        assert item["deducible"] == "Deducible"


def test_actualizar_flags_uuid_inexistente_y_aislamiento(db):
    assert db.actualizar_flags_cfdi("NO-EXISTE", RFC_B, {"deducible": None}) is None

    # Mismo uuid bajo dos empresas: apagar el toggle bajo B no roza la copia
    # de A (bajo A es emitida → ni siquiera es elegible).
    _cargar(db, _cfdi_ingreso_xml(), mi_rfc=RFC_A)
    _cargar(db, _cfdi_ingreso_xml(), mi_rfc=RFC_B)
    db.actualizar_flags_cfdi(UUID_INGRESO, RFC_B, {"incluir_diot": 0})
    (item_a,) = db.listar({"mi_rfc": RFC_A})["items"]
    (item_b,) = db.listar({"mi_rfc": RFC_B})["items"]
    assert item_a["incluir_diot"] is True and item_a["elegible_diot"] is False
    assert item_b["incluir_diot"] is False and item_b["elegible_diot"] is True


# ---------------------------------------------------------------------------
# Filtro «Estado DIOT» + contadores en stats + export
# ---------------------------------------------------------------------------


def _sembrar_cuatro(db) -> None:
    """Buffer de RFC_B: 2 recibidos I (uno excluido), 1 pago y 1 emitida."""
    _cargar(db, _cfdi_ingreso_xml(), mi_rfc=RFC_B)  # recibido, pasa
    _cargar(db, _cfdi_ingreso_xml(
        uuid="EXCLUIDO-1111-2222-3333-444444444444"), mi_rfc=RFC_B)
    _cargar(db, _cfdi_pago_xml(), mi_rfc=RFC_B)  # tipo P → no aplica
    _cargar(db, _cfdi_ingreso_xml(  # emitida por RFC_B → no aplica
        uuid="EMITIDA0-1111-2222-3333-444444444444",
        emisor_rfc=RFC_B, receptor_rfc="CCC030303CC9"), mi_rfc=RFC_B)
    db.actualizar_flags_cfdi(
        "EXCLUIDO-1111-2222-3333-444444444444", RFC_B, {"incluir_diot": 0}
    )


def test_filtro_diot_en_listar(db):
    _sembrar_cuatro(db)
    base = {"mi_rfc": RFC_B}
    assert db.listar({**base, "diot": "pasa"})["total"] == 1
    assert db.listar({**base, "diot": "excluido"})["total"] == 1
    assert db.listar({**base, "diot": "noaplica"})["total"] == 2
    assert db.listar(base)["total"] == 4  # sin filtro no se pierde nada


def test_stats_incluyen_contadores_diot_deducible(db):
    _sembrar_cuatro(db)
    db.actualizar_flags_cfdi(UUID_INGRESO, RFC_B, {"deducible": "No deducible"})

    stats = stats_generales(db, {"mi_rfc": RFC_B})
    assert stats["diot_elegibles"] == 2
    assert stats["diot_pasan"] == 1
    assert stats["diot_no_aplica"] == 2
    assert stats["deducible_no"] == 1
    assert stats["deducible_sin_clasificar"] == 3

    # Los contadores son GLOBALES (scope mi_rfc): un filtro de UI no los mueve.
    filtrado = stats_generales(db, {"mi_rfc": RFC_B, "tipo": "P"})
    assert filtrado["total_comprobantes"] == 1
    assert filtrado["diot_elegibles"] == 2

    # Buffer vacío: 0s, no NULLs.
    vacio = stats_generales(db, {"mi_rfc": "DDD040404DD4"})
    assert vacio["diot_elegibles"] == 0 and vacio["deducible_sin_clasificar"] == 0


def test_export_csv_trae_columnas_diot_deducible(db):
    _sembrar_cuatro(db)
    csv_texto = to_csv(db, {"mi_rfc": RFC_B}).decode("utf-8")
    header = csv_texto.splitlines()[0]
    assert header.endswith("Deducible,DIOT")
    assert "Pasa a DIOT" in csv_texto
    assert "Excluido" in csv_texto
    assert "No aplica" in csv_texto
    assert "Sin analizar" in csv_texto


# ---------------------------------------------------------------------------
# API: PATCH /procesador/cfdi/{uuid} + persistencia del filtro diot
# ---------------------------------------------------------------------------

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import server  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402


@pytest.fixture()
def client(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    return TestClient(server.app)


def test_api_patch_flags(client, db):
    _cargar(db, _cfdi_ingreso_xml(), mi_rfc=RFC_B)

    # Camino feliz: apagar el toggle + clasificar en una sola llamada.
    r = client.patch(
        f"/procesador/cfdi/{UUID_INGRESO}",
        json={"rfc": RFC_B, "incluir_diot": False, "deducible": "No deducible"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["item"]["incluir_diot"] is False
    assert body["item"]["deducible"] == "No deducible"
    assert body["contadores"]["diot_pasan"] == 0

    # 'Sin analizar' regresa la clasificación a NULL.
    r = client.patch(
        f"/procesador/cfdi/{UUID_INGRESO}",
        json={"rfc": RFC_B, "deducible": "Sin analizar"},
    )
    assert r.status_code == 200 and r.json()["item"]["deducible"] is None

    # Body sin nada que actualizar → 400.
    r = client.patch(f"/procesador/cfdi/{UUID_INGRESO}", json={"rfc": RFC_B})
    assert r.status_code == 400

    # uuid desconocido → 404.
    r = client.patch(
        "/procesador/cfdi/NO-EXISTE", json={"rfc": RFC_B, "incluir_diot": True}
    )
    assert r.status_code == 404


def test_api_patch_rechaza_diot_en_no_elegible(client, db):
    _cargar(db, _cfdi_pago_xml(), mi_rfc=RFC_B)
    r = client.patch(
        f"/procesador/cfdi/{UUID_PAGO}",
        json={"rfc": RFC_B, "incluir_diot": False},
    )
    assert r.status_code == 400
    assert "elegible" in r.json()["detail"]


def test_api_filtros_roundtrip_diot(client):
    """El filtro `diot` sobrevive el PUT/GET de filtros persistidos (si el
    campo faltara en ProcesadorFiltrosRequest, Pydantic lo droppearía)."""
    r = client.put(
        "/procesador/cfdi/filtros",
        json={"rfc": RFC_B, "tipo": "I", "diot": "excluido"},
    )
    assert r.status_code == 200
    r = client.get("/procesador/cfdi/filtros", params={"rfc": RFC_B})
    assert r.status_code == 200
    assert r.json()["diot"] == "excluido"
