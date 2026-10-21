"""Tests para cli.config_store — catálogo de empresas y tracking de solicitudes."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from sat_descarga.cli import config_store


@pytest.fixture(autouse=True)
def temp_config(tmp_path, monkeypatch):
    """Redirige CONFIG_DIR, EFIRMA_DIR y la carpeta de descargas a tmp.

    `descargas_dir_default` se parchea para que el respaldo visible de la e.firma
    (<descargas>/fiel/{RFC}/) NUNCA escriba en el ~/Documents real durante los tests.
    """
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.setattr(
        config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta")
    )


# ---------------------------------------------------------------------------
# Empresas
# ---------------------------------------------------------------------------

class TestEmpresas:

    def test_list_vacia_inicial(self):
        assert config_store.list_empresas() == []

    def test_add_empresa(self, test_cer, test_key, test_password, test_rfc):
        rfc = config_store.add_empresa("Mi Empresa", test_cer, test_key, test_password)
        assert rfc == test_rfc

    def test_add_copia_archivos(self, test_cer, test_key, test_password, tmp_path):
        rfc = config_store.add_empresa("Test", test_cer, test_key, test_password)
        efirma_dir = tmp_path / "efirma" / rfc
        assert (efirma_dir / "fiel.cer").exists()
        assert (efirma_dir / "fiel.key").exists()
        # La contraseña ya NO se escribe en texto plano (va al keychain).
        assert not (efirma_dir / "fiel.txt").exists()

    def test_respaldo_en_descargas(self, test_cer, test_key, test_password, tmp_path):
        rfc = config_store.add_empresa("Test", test_cer, test_key, test_password)
        backup = tmp_path / "TodoConta" / "fiel" / rfc
        assert (backup / "fiel.cer").exists()
        assert (backup / "fiel.key").exists()
        assert (backup / "LÉEME.txt").exists()

    def test_leeme_dice_donde_vive_la_efirma(
        self, test_cer, test_key, test_password, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("SAT_DM_MODO", raising=False)
        rfc = config_store.add_empresa("Test", test_cer, test_key, test_password)
        leeme = (tmp_path / "TodoConta" / "fiel" / rfc / "LÉEME.txt").read_text(encoding="utf-8")
        assert "se queda en este equipo" in leeme
        assert "NUNCA sube" not in leeme

    def test_leeme_en_la_web_no_dice_que_esta_en_tu_equipo(
        self, test_cer, test_key, test_password, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("SAT_DM_MODO", "hosted")
        rfc = config_store.add_empresa("Test", test_cer, test_key, test_password)
        leeme = (tmp_path / "TodoConta" / "fiel" / rfc / "LÉEME.txt").read_text(encoding="utf-8")
        assert "espacio privado" in leeme
        assert "este equipo" not in leeme

    def test_respaldo_no_guarda_password(self, test_cer, test_key, test_password, tmp_path):
        rfc = config_store.add_empresa("Test", test_cer, test_key, test_password)
        backup = tmp_path / "TodoConta" / "fiel" / rfc
        # La contraseña nunca se escribe en el respaldo (ni archivo aparte ni en el LÉEME).
        assert not (backup / "fiel.txt").exists()
        assert test_password not in (backup / "LÉEME.txt").read_text(encoding="utf-8")

    def test_respaldo_falla_no_rompe_registro(
        self, test_cer, test_key, test_password, test_rfc, tmp_path, monkeypatch
    ):
        # Carpeta de descargas "imposible" (un archivo, no un dir) → el respaldo falla,
        # pero el alta debe completarse igual (best-effort, solo warning).
        bloqueo = tmp_path / "no_es_carpeta"
        bloqueo.write_text("x")
        monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(bloqueo))
        rfc = config_store.add_empresa("Test", test_cer, test_key, test_password)
        assert rfc == test_rfc
        assert config_store.get_empresa(rfc)["cer_path"]  # quedó registrada

    def test_password_no_queda_en_disco_plano(self, test_cer, test_key, test_password, tmp_path):
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        contenido_json = (tmp_path / ".sat-descarga" / "empresas.json").read_text()
        assert test_password not in contenido_json  # no se filtra al catálogo

    def test_get_empresa_recupera_password_del_keychain(self, test_cer, test_key, test_password, test_rfc):
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        assert config_store.get_empresa(test_rfc)["password"] == test_password

    def test_add_empresa_ciec(self):
        rfc = config_store.add_empresa_ciec("CAUI890921DAA", "Cliente CIEC", "miCiec123")
        assert rfc == "CAUI890921DAA"
        empresa = config_store.get_empresa(rfc)
        assert empresa["metodos"] == ["ciec"]
        assert empresa["ciec"] == "miCiec123"
        assert config_store.list_empresas()[0]["metodos"] == ["ciec"]

    def test_update_empresa_presenta_diot(self):
        """Override manual de la obligación DIOT: bool editable; ausente = None
        (la UI lo deriva del régimen configurado, RESICO relevado)."""
        rfc = config_store.add_empresa_ciec("CAUI890921DAA", "Cliente CIEC", "miCiec123")
        assert config_store.list_empresas()[0]["presenta_diot"] is None

        config_store.update_empresa(rfc, {"presenta_diot": False})
        assert config_store.list_empresas()[0]["presenta_diot"] is False
        config_store.update_empresa(rfc, {"presenta_diot": True})
        assert config_store.list_empresas()[0]["presenta_diot"] is True

        with pytest.raises(ValueError):
            config_store.update_empresa(rfc, {"presenta_diot": "no"})
        # Los campos de lista siguen validando su shape (no rompimos la rama).
        with pytest.raises(ValueError):
            config_store.update_empresa(rfc, {"regimenes_fiscales": "626"})

    def test_empresa_puede_tener_ambos_metodos(self, test_cer, test_key, test_password, test_rfc):
        # Primero CIEC, luego e.firma para el MISMO RFC → conserva ambos.
        config_store.add_empresa_ciec(test_rfc, "Mi Empresa", "miCiec")
        config_store.add_empresa("Mi Empresa", test_cer, test_key, test_password)
        empresa = config_store.get_empresa(test_rfc)
        assert sorted(empresa["metodos"]) == ["ciec", "fiel"]
        assert empresa["ciec"] == "miCiec"           # credencial CIEC sigue ahí
        assert empresa["password"] == test_password  # + la de la e.firma
        assert "cer_path" in empresa
        # Una sola empresa en el catálogo (se fusionó, no se duplicó).
        assert len(config_store.list_empresas()) == 1

    def test_add_fiel_rfc_esperado_rechaza_ajena(self, test_cer, test_key, test_password):
        # Subir una e.firma cuyo RFC no coincide con el esperado → se rechaza.
        with pytest.raises(ValueError, match="corresponde al RFC"):
            config_store.add_empresa(
                "X", test_cer, test_key, test_password, rfc_esperado="OTRO000000XX1",
            )
        assert config_store.list_empresas() == []  # no quedó registrada

    def test_add_fiel_rfc_esperado_coincide(self, test_cer, test_key, test_password, test_rfc):
        rfc = config_store.add_empresa(
            "X", test_cer, test_key, test_password, rfc_esperado=test_rfc,
        )
        assert rfc == test_rfc

    def test_remove_borra_credenciales(self, test_cer, test_key, test_password, test_rfc):
        from sat_descarga.core import secretos
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        assert secretos.obtener(test_rfc, secretos.FIEL) == test_password
        config_store.remove_empresa(test_rfc)
        assert secretos.obtener(test_rfc, secretos.FIEL) is None

    def test_add_guarda_vencimiento(self, test_cer, test_key, test_password):
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        empresas = config_store.list_empresas()
        assert empresas[0]["vencimiento"] != ""

    def test_primera_empresa_es_default(self, test_cer, test_key, test_password, test_rfc):
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        assert config_store.get_default() == test_rfc

    def test_list_retorna_empresa(self, test_cer, test_key, test_password, test_rfc):
        config_store.add_empresa("Mi Empresa", test_cer, test_key, test_password)
        empresas = config_store.list_empresas()
        assert len(empresas) == 1
        assert empresas[0]["rfc"] == test_rfc
        assert empresas[0]["nombre"] == "Mi Empresa"
        assert empresas[0]["default"] is True

    def test_get_empresa(self, test_cer, test_key, test_password, test_rfc):
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        empresa = config_store.get_empresa(test_rfc)
        assert empresa["rfc"] == test_rfc
        assert "cer_path" in empresa
        assert "password" in empresa

    def test_get_empresa_inexistente(self):
        with pytest.raises(KeyError):
            config_store.get_empresa("RFC_QUE_NO_EXISTE")

    def test_remove_empresa(self, test_cer, test_key, test_password, test_rfc):
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        config_store.remove_empresa(test_rfc)
        assert config_store.list_empresas() == []

    def test_remove_default_asigna_otro(self, test_cer, test_key, test_password, test_rfc):
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        config_store.remove_empresa(test_rfc)
        assert config_store.get_default() is None

    def test_set_default(self, test_cer, test_key, test_password, test_rfc):
        config_store.add_empresa("Test", test_cer, test_key, test_password)
        config_store.set_default(test_rfc)
        assert config_store.get_default() == test_rfc

    def test_set_default_inexistente(self):
        with pytest.raises(KeyError):
            config_store.set_default("NO_EXISTE")


class TestActualizarNombreSiPlaceholder:
    """Auto-corrección del nombre cuando quedó como placeholder (== RFC).

    Pasa cuando la extracción del nombre del cert falló al dar de alta (p. ej.
    cert con Ñ); se corrige solo al cargar la e.firma, sin borrar y re-agregar.
    """

    RFC = "CAUI890921DAA"

    def _alta_con_nombre_placeholder(self):
        # add_empresa_ciec con nombre vacío deja el RFC como nombre.
        config_store.add_empresa_ciec(self.RFC, "", "ciec")

    def test_actualiza_cuando_nombre_es_el_rfc(self):
        self._alta_con_nombre_placeholder()
        assert config_store.actualizar_nombre_si_placeholder(self.RFC, "Israel Castro") is True
        emp = config_store.get_empresa(self.RFC)
        assert emp["nombre"] == "Israel Castro"

    def test_no_pisa_un_nombre_real(self):
        config_store.add_empresa_ciec(self.RFC, "Nombre Real", "ciec")
        assert config_store.actualizar_nombre_si_placeholder(self.RFC, "Otro") is False
        assert config_store.get_empresa(self.RFC)["nombre"] == "Nombre Real"

    def test_ignora_nombre_nuevo_vacio_o_igual_al_rfc(self):
        self._alta_con_nombre_placeholder()
        assert config_store.actualizar_nombre_si_placeholder(self.RFC, "") is False
        assert config_store.actualizar_nombre_si_placeholder(self.RFC, self.RFC) is False
        assert config_store.get_empresa(self.RFC)["nombre"] == self.RFC

    def test_rfc_inexistente_devuelve_false(self):
        assert config_store.actualizar_nombre_si_placeholder("XXXX010101XXX", "N") is False


class TestAplicarDatosCsf:
    """Aplicación de los datos parseados de la CSF: la constancia MANDA."""

    RFC = "SAJ0205248A9"
    REGIMENES = [{"clave": "601", "descripcion": "Régimen General de Ley Personas Morales"}]
    ACTIVIDADES = [
        {"descripcion": "Comercio al por menor de gasolina y diésel",
         "principal": True, "porcentaje": 99},
        {"descripcion": "Comercio al por menor de aceites y grasas lubricantes",
         "principal": False, "porcentaje": 1},
    ]

    def _aplicar(self, nombre="SUPERSERVICIO AJUCHITLAN"):
        return config_store.aplicar_datos_csf(
            self.RFC, nombre=nombre,
            regimenes=self.REGIMENES, actividades=self.ACTIVIDADES,
        )

    def test_sobrescribe_nombre_no_placeholder(self):
        # A diferencia de actualizar_nombre_si_placeholder, aquí la CSF manda
        # incluso sobre un nombre "real" (unifica casing y errores de captura).
        config_store.add_empresa_ciec(self.RFC, "nombre Mal capturado", "ciec")
        assert self._aplicar() is True
        emp = config_store.get_empresa(self.RFC)
        assert emp["nombre"] == "SUPERSERVICIO AJUCHITLAN"

    def test_sobrescribe_configuracion_manual(self):
        config_store.add_empresa_ciec(self.RFC, "X", "ciec")
        config_store.update_empresa(self.RFC, {
            "regimenes_fiscales": [{"clave": "626", "descripcion": "RESICO a mano"}],
            "actividades_economicas": [{"descripcion": "Otra cosa", "principal": True}],
        })
        self._aplicar()
        emp = config_store.get_empresa(self.RFC)
        assert emp["regimenes_fiscales"] == self.REGIMENES
        assert emp["actividades_economicas"] == self.ACTIVIDADES

    def test_estampa_updated_at(self):
        config_store.add_empresa_ciec(self.RFC, "X", "ciec")
        antes = config_store.get_empresa(self.RFC).get("updated_at")
        with patch.object(config_store, "_ahora_sync", return_value="2099-01-01T00:00:00+00:00"):
            self._aplicar()
        despues = config_store.get_empresa(self.RFC).get("updated_at")
        assert despues == "2099-01-01T00:00:00+00:00" and despues != antes

    def test_nombre_vacio_no_pisa_el_existente(self):
        config_store.add_empresa_ciec(self.RFC, "Nombre Actual", "ciec")
        assert self._aplicar(nombre="  ") is True
        emp = config_store.get_empresa(self.RFC)
        assert emp["nombre"] == "Nombre Actual"
        assert emp["regimenes_fiscales"] == self.REGIMENES

    def test_porcentaje_none_se_omite(self):
        config_store.add_empresa_ciec(self.RFC, "X", "ciec")
        config_store.aplicar_datos_csf(
            self.RFC, nombre="X",
            regimenes=[],
            actividades=[{"descripcion": "Sin dato", "principal": True, "porcentaje": None}],
        )
        actividad = config_store.get_empresa(self.RFC)["actividades_economicas"][0]
        assert "porcentaje" not in actividad

    def test_rfc_inexistente_devuelve_false(self):
        assert config_store.aplicar_datos_csf(
            "XXXX010101XXX", nombre="N", regimenes=[], actividades=[],
        ) is False


class TestUpdateEmpresaPorcentaje:
    """`porcentaje` opcional en actividades (viene del parser de la CSF)."""

    RFC = "CAUI890921DAA"

    def _alta(self):
        config_store.add_empresa_ciec(self.RFC, "X", "ciec")

    def test_acepta_y_persiste_porcentaje(self):
        self._alta()
        config_store.update_empresa(self.RFC, {
            "actividades_economicas": [
                {"descripcion": "Asalariado", "principal": True, "porcentaje": 75},
                {"descripcion": "Contabilidad", "porcentaje": 25},
            ],
        })
        actividades = config_store.get_empresa(self.RFC)["actividades_economicas"]
        assert actividades[0]["porcentaje"] == 75
        assert actividades[1] == {"descripcion": "Contabilidad", "porcentaje": 25}

    def test_rechaza_porcentaje_no_numerico(self):
        self._alta()
        with pytest.raises(ValueError):
            config_store.update_empresa(self.RFC, {
                "actividades_economicas": [{"descripcion": "A", "porcentaje": "75%"}],
            })

    def test_sin_porcentaje_sigue_funcionando(self):
        self._alta()
        config_store.update_empresa(self.RFC, {
            "actividades_economicas": [{"descripcion": "A", "principal": True}],
        })
        actividad = config_store.get_empresa(self.RFC)["actividades_economicas"][0]
        assert actividad == {"descripcion": "A", "principal": True}

    def test_update_empresa_estampa_updated_at(self):
        # Régimen/actividades/DIOT ahora viajan en el sync: una edición manual
        # debe bumpear updated_at para propagarse a la otra instalación.
        self._alta()
        with patch.object(config_store, "_ahora_sync", return_value="2099-01-01T00:00:00+00:00"):
            config_store.update_empresa(self.RFC, {"presenta_diot": True})
        assert config_store.get_empresa(self.RFC).get("updated_at") == "2099-01-01T00:00:00+00:00"


class TestAplicarDatosOpinion:
    """Sentido + motivos de la Opinión 32-D → semáforo de la empresa."""

    RFC = "CAUI890921DAA"
    MOTIVOS = [
        {"titulo": "Créditos fiscales",
         "descripcion": "Se ubican los siguientes créditos fiscales firmes o no garantizados a su cargo:",
         "detalles": ["234910013510"]},
        {"titulo": "Cumplimiento de obligaciones",
         "descripcion": "Se detectan omisiones ...:",
         "detalles": ["Pago provisional mensual de ISR ...", "Ejercicio 2022"]},
    ]

    def test_negativa_guarda_status_y_motivos(self):
        config_store.add_empresa_ciec(self.RFC, "Israel", "ciec")
        assert config_store.aplicar_datos_opinion(
            self.RFC, sentido="negativa", motivos=self.MOTIVOS) is True
        emp = config_store.get_empresa(self.RFC)
        assert emp["opinion_status"] == "negativa"
        assert [m["titulo"] for m in emp["opinion_motivos"]] == [
            "Créditos fiscales", "Cumplimiento de obligaciones"]
        assert emp["opinion_motivos"][0]["detalles"] == ["234910013510"]

    def test_positiva_limpia_motivos(self):
        config_store.add_empresa_ciec(self.RFC, "Israel", "ciec")
        config_store.aplicar_datos_opinion(self.RFC, sentido="negativa", motivos=self.MOTIVOS)
        # Una nueva descarga positiva debe dejar el semáforo verde y sin motivos.
        config_store.aplicar_datos_opinion(self.RFC, sentido="positiva", motivos=[])
        emp = config_store.get_empresa(self.RFC)
        assert emp["opinion_status"] == "positiva"
        assert emp["opinion_motivos"] == []

    def test_expuesto_en_list_empresas(self):
        config_store.add_empresa_ciec(self.RFC, "Israel", "ciec")
        config_store.aplicar_datos_opinion(self.RFC, sentido="negativa", motivos=self.MOTIVOS)
        emp = config_store.list_empresas()[0]
        assert emp["opinion_status"] == "negativa"
        assert len(emp["opinion_motivos"]) == 2

    def test_rfc_inexistente_devuelve_false(self):
        assert config_store.aplicar_datos_opinion(
            "XXXX010101XXX", sentido="negativa", motivos=[]) is False


# ---------------------------------------------------------------------------
# Solicitudes
# ---------------------------------------------------------------------------

class TestSolicitudes:

    def test_sin_solicitudes(self, test_rfc):
        assert config_store.get_solicitudes_pendientes(test_rfc) == []

    def test_save_solicitud(self, test_rfc):
        config_store.save_solicitud(
            rfc=test_rfc,
            id_solicitud="abc-123",
            fecha_inicio="2025-01-01",
            fecha_fin="2025-12-31",
            tipo="E",
        )
        pendientes = config_store.get_solicitudes_pendientes(test_rfc)
        assert len(pendientes) == 1
        assert pendientes[0]["id_solicitud"] == "abc-123"

    def test_get_solicitud(self, test_rfc):
        config_store.save_solicitud(
            rfc=test_rfc, id_solicitud="xyz-789",
            fecha_inicio="2025-01-01", fecha_fin="2025-06-30", tipo="R",
        )
        sol = config_store.get_solicitud(test_rfc, "xyz-789")
        assert sol is not None
        assert sol["tipo"] == "R"

    def test_get_solicitud_inexistente(self, test_rfc):
        assert config_store.get_solicitud(test_rfc, "no-existe") is None

    def test_update_solicitud(self, test_rfc):
        config_store.save_solicitud(
            rfc=test_rfc, id_solicitud="upd-001",
            fecha_inicio="2025-01-01", fecha_fin="2025-12-31", tipo="E",
        )
        config_store.update_solicitud(test_rfc, "upd-001", "terminada", ["pkg1", "pkg2"])
        sol = config_store.get_solicitud(test_rfc, "upd-001")
        assert sol["estado"] == "terminada"
        assert sol["package_ids"] == ["pkg1", "pkg2"]

    def test_pendientes_excluye_terminadas(self, test_rfc):
        config_store.save_solicitud(
            rfc=test_rfc, id_solicitud="s1",
            fecha_inicio="2025-01-01", fecha_fin="2025-12-31", tipo="E",
        )
        config_store.save_solicitud(
            rfc=test_rfc, id_solicitud="s2",
            fecha_inicio="2025-01-01", fecha_fin="2025-12-31", tipo="R",
        )
        config_store.update_solicitud(test_rfc, "s1", "terminada")
        pendientes = config_store.get_solicitudes_pendientes(test_rfc)
        assert len(pendientes) == 1
        assert pendientes[0]["id_solicitud"] == "s2"

    def test_pendientes_excluye_vencidas_y_descargadas(self, test_rfc):
        for i, estado in enumerate(["2", "vencida", "descargada", "4", "5", "3"]):
            config_store.save_solicitud(
                rfc=test_rfc, id_solicitud=f"p{i}",
                fecha_inicio="2025-01-01", fecha_fin="2025-12-31", tipo="E",
            )
            config_store.update_solicitud(test_rfc, f"p{i}", estado)
        pendientes = config_store.get_solicitudes_pendientes(test_rfc)
        assert [p["id_solicitud"] for p in pendientes] == ["p0"]


class TestSolicitudesVencimiento:
    """`marcar_solicitudes_vencidas`: cierra lo que el SAT dejó colgado >72 h."""

    def _solicitud(self, rfc, id_sol, estado="2", timestamp=None):
        config_store.save_solicitud(
            rfc=rfc, id_solicitud=id_sol,
            fecha_inicio="2025-01-01", fecha_fin="2025-12-31", tipo="E",
        )
        if estado != "solicitada":
            config_store.update_solicitud(rfc, id_sol, estado)
        if timestamp is not None:
            # Manipula el timestamp directamente en el JSON (simula antigüedad).
            path = config_store._solicitudes_path(rfc)
            data = json.loads(path.read_text(encoding="utf-8"))
            for s in data["solicitudes"]:
                if s["id_solicitud"] == id_sol:
                    if timestamp == "":
                        s.pop("timestamp", None)
                    else:
                        s["timestamp"] = timestamp
            path.write_text(json.dumps(data), encoding="utf-8")

    def test_reciente_no_vence(self, test_rfc):
        self._solicitud(test_rfc, "fresca", estado="2")
        assert config_store.marcar_solicitudes_vencidas(test_rfc) == []
        assert config_store.get_solicitud(test_rfc, "fresca")["estado"] == "2"

    def test_vieja_pendiente_vence(self, test_rfc):
        from datetime import datetime, timedelta
        vieja = (datetime.now() - timedelta(hours=100)).isoformat(timespec="seconds")
        self._solicitud(test_rfc, "colgada", estado="2", timestamp=vieja)
        vencidas = config_store.marcar_solicitudes_vencidas(test_rfc)
        assert [v["id_solicitud"] for v in vencidas] == ["colgada"]
        sol = config_store.get_solicitud(test_rfc, "colgada")
        assert sol["estado"] == "vencida"
        assert "72 horas" in sol["mensaje"]

    def test_vieja_terminal_no_se_toca(self, test_rfc):
        from datetime import datetime, timedelta
        vieja = (datetime.now() - timedelta(hours=100)).isoformat(timespec="seconds")
        self._solicitud(test_rfc, "bajada", estado="descargada", timestamp=vieja)
        self._solicitud(test_rfc, "lista", estado="3", timestamp=vieja)
        assert config_store.marcar_solicitudes_vencidas(test_rfc) == []
        assert config_store.get_solicitud(test_rfc, "bajada")["estado"] == "descargada"
        assert config_store.get_solicitud(test_rfc, "lista")["estado"] == "3"

    def test_sin_timestamp_es_legacy_y_vence(self, test_rfc):
        self._solicitud(test_rfc, "legacy", estado="1", timestamp="")
        vencidas = config_store.marcar_solicitudes_vencidas(test_rfc)
        assert [v["id_solicitud"] for v in vencidas] == ["legacy"]

    def test_idempotente(self, test_rfc):
        from datetime import datetime, timedelta
        vieja = (datetime.now() - timedelta(hours=100)).isoformat(timespec="seconds")
        self._solicitud(test_rfc, "colgada", estado="2", timestamp=vieja)
        assert len(config_store.marcar_solicitudes_vencidas(test_rfc)) == 1
        assert config_store.marcar_solicitudes_vencidas(test_rfc) == []


# ---------------------------------------------------------------------------
# Concurrencia y escritura atómica del catálogo
# ---------------------------------------------------------------------------

class TestCatalogoConcurrente:

    def test_escrituras_concurrentes_no_pierden_empresas(self):
        """Sin el lock del catálogo, N hilos haciendo read-modify-write sobre
        empresas.json se pisaban entre sí (TOCTOU) y se perdían altas."""
        import threading

        rfcs = [f"AAA{i:03d}0101AB{i % 10}" for i in range(12)]
        hilos = [
            threading.Thread(
                target=config_store.add_empresa_ciec,
                args=(rfc, f"Empresa {rfc}", "ciec123"),
            )
            for rfc in rfcs
        ]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        registradas = {e["rfc"] for e in config_store.list_empresas()}
        assert registradas == set(rfcs)

    def test_save_empresas_no_deja_tmp(self, tmp_path):
        config_store.add_empresa_ciec("CAUI890921DAA", "Test", "ciec")
        residuos = list((tmp_path / ".sat-descarga").glob("*.tmp"))
        assert residuos == []


# ---------------------------------------------------------------------------
# Resiliencia a corrupción de empresas.json (TODOCONTA-DESKTOP-N / -H)
# ---------------------------------------------------------------------------

class TestCatalogoCorrupto:
    """Tras un apagado abrupto en Windows, empresas.json quedaba lleno de NUL y
    `load_empresas` reventaba con JSONDecodeError en CADA request (la app quedaba
    inservible). Ahora se aísla el corrupto y el catálogo se reinicia."""

    def test_empresas_lleno_de_nul_no_revienta(self, tmp_path):
        config_store.add_empresa_ciec("CAUI890921DAA", "Test", "ciec")
        path = tmp_path / ".sat-descarga" / "empresas.json"
        path.write_bytes(b"\x00" * 128)  # firma exacta del crash de Windows

        # No debe lanzar: reinicia el catálogo en vez de tumbar /empresas.
        assert config_store.list_empresas() == []
        assert config_store.load_empresas() == {"empresas": {}, "default_rfc": None}

    def test_empresas_corrupto_se_aisla(self, tmp_path):
        config_store.add_empresa_ciec("CAUI890921DAA", "Test", "ciec")
        path = tmp_path / ".sat-descarga" / "empresas.json"
        path.write_bytes(b"\x00" * 128)

        config_store.load_empresas()
        assert not path.exists(), "el corrupto no debe quedar en su lugar"
        assert path.with_suffix(".json.corrupto").exists(), "debe quedar la cuarentena"

    def test_cuarentena_no_pisa_previa(self, tmp_path):
        d = tmp_path / ".sat-descarga"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "empresas.json"
        path.write_bytes(b"basura no-json")
        config_store.load_empresas()
        path.write_bytes(b"otra basura")
        config_store.load_empresas()
        assert (d / "empresas.json.corrupto").exists()
        assert (d / "empresas.json.corrupto1").exists()

    def test_escritura_es_durable_y_valida(self, tmp_path):
        """Tras un alta, empresas.json es JSON válido y legible (el fsync va
        antes del rename, así que no hay ventana de archivo a medias)."""
        config_store.add_empresa_ciec("CAUI890921DAA", "Test", "ciec")
        path = tmp_path / ".sat-descarga" / "empresas.json"
        cargado = json.loads(path.read_text(encoding="utf-8"))
        assert "CAUI890921DAA" in cargado["empresas"]


# ---------------------------------------------------------------------------
# Encoding legacy (TODOCONTA-DESKTOP-V)
# ---------------------------------------------------------------------------

NOMBRE_ACENTOS = "CONSTRUCCIÓN Y DISEÑO SA DE CV"


class TestEncodingLegacy:
    """Hasta v1.3.0, en Windows los JSON se escribían con `write_text()` sin
    `encoding=` → code page ANSI (cp1252). Un nombre con acentos NO es UTF-8
    válido, y v1.4.0/v1.5.0 lo trataba como corrupción: cuarentena + catálogo
    vacío (el usuario "perdía" sus empresas al actualizar). Ahora se rescata
    con el encoding correcto y se migra a UTF-8."""

    def _catalogo_legacy(self) -> dict:
        return {
            "empresas": {
                "CAUI890921DAA": {"nombre": NOMBRE_ACENTOS, "metodos": ["fiel"]},
            },
            "default_rfc": "CAUI890921DAA",
        }

    def _escribir_cp1252(self, path, data):
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        path.write_bytes(payload.encode("cp1252"))

    def test_catalogo_cp1252_se_rescata_y_migra(self, tmp_path):
        d = tmp_path / ".sat-descarga"
        d.mkdir(parents=True, exist_ok=True)
        self._escribir_cp1252(d / "empresas.json", self._catalogo_legacy())

        cargado = config_store.load_empresas()
        assert cargado["empresas"]["CAUI890921DAA"]["nombre"] == NOMBRE_ACENTOS
        # No hubo cuarentena y el archivo quedó migrado a UTF-8 en disco.
        assert not (d / "empresas.json.corrupto").exists()
        en_disco = json.loads((d / "empresas.json").read_text(encoding="utf-8"))
        assert en_disco["empresas"]["CAUI890921DAA"]["nombre"] == NOMBRE_ACENTOS

    def test_rescate_de_cuarentena_previa(self, tmp_path):
        """v1.4.0/v1.5.0 ya puso el catálogo en cuarentena: al cargar sin
        empresas.json, se restaura desde el .corrupto y este se archiva."""
        d = tmp_path / ".sat-descarga"
        d.mkdir(parents=True, exist_ok=True)
        self._escribir_cp1252(d / "empresas.json.corrupto", self._catalogo_legacy())

        cargado = config_store.load_empresas()
        assert cargado["empresas"]["CAUI890921DAA"]["nombre"] == NOMBRE_ACENTOS
        assert (d / "empresas.json").exists(), "el catálogo restaurado debe persistirse"
        assert (d / "empresas.json.corrupto.rescatado").exists()
        assert not (d / "empresas.json.corrupto").exists()

    def test_rescate_no_pisa_catalogo_existente(self, tmp_path):
        """Si el usuario ya re-registró empresas tras la cuarentena (hay un
        empresas.json vigente), el .corrupto viejo NO debe pisarlo."""
        d = tmp_path / ".sat-descarga"
        d.mkdir(parents=True, exist_ok=True)
        self._escribir_cp1252(d / "empresas.json.corrupto", self._catalogo_legacy())
        (d / "empresas.json").write_text(json.dumps({
            "empresas": {"XAXX010101000": {"nombre": "Re-registrada", "metodos": ["ciec"]}},
            "default_rfc": "XAXX010101000",
        }), encoding="utf-8")

        cargado = config_store.load_empresas()
        assert list(cargado["empresas"]) == ["XAXX010101000"]
        assert (d / "empresas.json.corrupto").exists(), "la cuarentena queda para forense"

    def test_rescate_aplica_antes_del_primer_alta(self, tmp_path):
        """Si el rescate sigue pendiente cuando el usuario da de alta una
        empresa, primero se restaura el catálogo y el alta se agrega encima
        (recupera todo + lo nuevo)."""
        d = tmp_path / ".sat-descarga"
        d.mkdir(parents=True, exist_ok=True)
        self._escribir_cp1252(d / "empresas.json.corrupto", self._catalogo_legacy())
        config_store.add_empresa_ciec("XAXX010101000", "Nueva", "ciec")

        cargado = config_store.load_empresas()
        assert set(cargado["empresas"]) == {"CAUI890921DAA", "XAXX010101000"}

    def test_cuarentena_nul_no_es_rescatable(self, tmp_path):
        """La corrupción real (NUL tras apagado abrupto) sigue en cuarentena y
        no dispara falsos rescates."""
        d = tmp_path / ".sat-descarga"
        d.mkdir(parents=True, exist_ok=True)
        (d / "empresas.json").write_bytes(b"\x00" * 128)

        assert config_store.load_empresas() == {"empresas": {}, "default_rfc": None}
        assert (d / "empresas.json.corrupto").exists()
        # Segunda carga: no hay empresas.json, el .corrupto NUL no parsea → vacío.
        assert config_store.load_empresas() == {"empresas": {}, "default_rfc": None}

    def test_solicitudes_cp1252_se_migran(self, tmp_path):
        d = tmp_path / ".sat-descarga" / "solicitudes"
        d.mkdir(parents=True, exist_ok=True)
        data = {"solicitudes": [{
            "id_solicitud": "abc-123", "fecha_inicio": "2026-01-01",
            "fecha_fin": "2026-01-31", "tipo": "emitidos", "estado": "terminada",
            "mensaje": "Petición atendida con éxito",
        }]}
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        (d / "CAUI890921DAA.json").write_bytes(payload.encode("cp1252"))

        sols = config_store.list_solicitudes("CAUI890921DAA")
        assert sols[0]["mensaje"] == "Petición atendida con éxito"
        en_disco = json.loads((d / "CAUI890921DAA.json").read_text(encoding="utf-8"))
        assert en_disco["solicitudes"][0]["mensaje"] == "Petición atendida con éxito"

    def test_settings_cp1252_se_rescatan(self, tmp_path):
        d = tmp_path / ".sat-descarga"
        d.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"descargas_dir": "C:\\Users\\José\\Documents\\TodoConta"},
                             ensure_ascii=False)
        (d / "settings.json").write_bytes(payload.encode("cp1252"))

        assert config_store.get_descargas_dir() == "C:\\Users\\José\\Documents\\TodoConta"
        assert not (d / "settings.json.corrupto").exists()

    def test_historial_cp1252_se_rescata(self, tmp_path):
        d = tmp_path / ".sat-descarga" / "historial"
        d.mkdir(parents=True, exist_ok=True)
        data = {"descargas": [{"timestamp": "2026-06-01T10:00:00", "canal": "ciec",
                               "tipo": "cfdi", "descripcion": "Recibidos de MUÑOZ"}]}
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        (d / "CAUI890921DAA.json").write_bytes(payload.encode("cp1252"))

        descargas = config_store.list_descargas("CAUI890921DAA")
        assert descargas[0]["descripcion"] == "Recibidos de MUÑOZ"
        todas = config_store.list_todas_descargas()
        assert todas[0]["descripcion"] == "Recibidos de MUÑOZ"


# ---------------------------------------------------------------------------
# Certifica: renovación de e.firma y CSDs
# ---------------------------------------------------------------------------

class TestCertifica:

    def _alta(self, test_cer, test_key, test_password):
        return config_store.add_empresa("Test", test_cer, test_key, test_password)

    # -- respaldo de la e.firma anterior --

    def test_respaldar_efirma_anterior(self, test_cer, test_key, test_password, tmp_path):
        rfc = self._alta(test_cer, test_key, test_password)
        destino = config_store.respaldar_efirma_anterior(rfc)
        assert destino is not None and destino.name.startswith("anterior_")
        assert (destino / "fiel.cer").exists()
        assert (destino / "fiel.key").exists()
        # Los originales siguen en su lugar (es copia, no move).
        assert (tmp_path / "efirma" / rfc / "fiel.cer").exists()

    def test_respaldar_sin_efirma_devuelve_none(self):
        assert config_store.respaldar_efirma_anterior("XAXX010101000") is None

    # -- renovación pendiente --

    def test_renovacion_pendiente_ciclo(self, test_cer, test_key, test_password):
        rfc = self._alta(test_cer, test_key, test_password)
        assert config_store.get_renovacion_pendiente(rfc) is None

        config_store.set_renovacion_pendiente(rfc, {
            "numero_operacion": "123456", "acuse_pdf": "/tmp/acuse.pdf",
            "key_path": "/tmp/nueva.key",
        })
        pendiente = config_store.get_renovacion_pendiente(rfc)
        assert pendiente["numero_operacion"] == "123456"
        assert pendiente["solicitado_en"]  # timestamp automático

        # Aparece en el payload de list_empresas (lo lee la UI).
        emp = next(e for e in config_store.list_empresas() if e["rfc"] == rfc)
        assert emp["renovacion_pendiente"]["numero_operacion"] == "123456"

        config_store.clear_renovacion_pendiente(rfc)
        assert config_store.get_renovacion_pendiente(rfc) is None

    def test_renovacion_pendiente_rfc_inexistente_no_lanza(self):
        config_store.set_renovacion_pendiente("XAXX010101000", {"numero_operacion": "1"})
        assert config_store.get_renovacion_pendiente("XAXX010101000") is None
        config_store.clear_renovacion_pendiente("XAXX010101000")  # no lanza

    # -- CSDs --

    def test_registrar_y_actualizar_csd(self, test_cer, test_key, test_password):
        rfc = self._alta(test_cer, test_key, test_password)
        registro = config_store.registrar_csd(rfc, {
            "uso": "Facturación general", "numero_operacion": "987654",
            "acuse_pdf": "/tmp/acuse_csd.pdf", "key_path": "/tmp/csd.key",
        })
        assert registro["estado"] == "pendiente"
        assert registro["cer_path"] is None

        assert config_store.get_csd_pendiente(rfc)["numero_operacion"] == "987654"
        assert config_store.get_csd_pendiente(rfc, "987654") is not None
        assert config_store.get_csd_pendiente(rfc, "otro") is None

        ok = config_store.update_csd(rfc, "987654", {
            "estado": "emitido", "cer_path": "/tmp/csd.cer",
            "recuperado_en": "2026-07-09T10:00:00",
        })
        assert ok
        emp = next(e for e in config_store.list_empresas() if e["rfc"] == rfc)
        assert emp["csds"][0]["estado"] == "emitido"
        assert config_store.get_csd_pendiente(rfc) is None  # ya no hay pendientes

    def test_csd_pendiente_toma_el_mas_reciente(self, test_cer, test_key, test_password):
        rfc = self._alta(test_cer, test_key, test_password)
        config_store.registrar_csd(rfc, {"uso": "Matriz", "numero_operacion": "111",
                                         "acuse_pdf": None, "key_path": "/tmp/a.key"})
        config_store.registrar_csd(rfc, {"uso": "Sucursal", "numero_operacion": "222",
                                         "acuse_pdf": None, "key_path": "/tmp/b.key"})
        assert config_store.get_csd_pendiente(rfc)["numero_operacion"] == "222"

    def test_update_csd_inexistente(self, test_cer, test_key, test_password):
        rfc = self._alta(test_cer, test_key, test_password)
        assert config_store.update_csd(rfc, "nope", {"estado": "emitido"}) is False
        assert config_store.update_csd("XAXX010101000", "1", {}) is False

    def test_registrar_csd_rfc_inexistente_lanza(self):
        with pytest.raises(KeyError):
            config_store.registrar_csd("XAXX010101000", {"uso": "x", "numero_operacion": "1",
                                                         "acuse_pdf": None, "key_path": "k"})


# ---------------------------------------------------------------------------
# Config del organizador (GLOBAL por usuario)
# ---------------------------------------------------------------------------

class TestOrganizadorConfig:

    def test_defaults_sin_guardar(self):
        cfg = config_store.get_organizador_config()
        assert cfg["guardada"] is False
        assert cfg["estructura"] == "rfc_emisor/anio/mes"
        assert cfg["niveles_custom"] == ["anio", "mes", "flujo"]
        assert cfg["copiar"] is True

    def test_patch_parcial_hace_merge(self):
        config_store.set_organizador_config(
            {"estructura": "custom", "niveles_custom": ["rfc", "anio", "mes"]}
        )
        config_store.set_organizador_config({"separador": "_"})

        cfg = config_store.get_organizador_config()
        assert cfg["guardada"] is True
        assert cfg["estructura"] == "custom"
        assert cfg["niveles_custom"] == ["rfc", "anio", "mes"]
        assert cfg["separador"] == "_"
        # Lo no tocado conserva su default
        assert cfg["copiar"] is True
        assert cfg["renombrar_patron"] == "emisor_fecha_total"

    def test_ignora_claves_desconocidas(self):
        config_store.set_organizador_config({"inyectada": "x", "copiar": False})
        cfg = config_store.get_organizador_config()
        assert "inyectada" not in cfg
        assert cfg["copiar"] is False

    def test_persiste_en_settings_json(self):
        config_store.set_organizador_config({"renombrar_patron": "uuid"})
        raw = json.loads(
            (config_store.get_config_dir() / "settings.json").read_text(encoding="utf-8")
        )
        assert raw["organizador"]["renombrar_patron"] == "uuid"
