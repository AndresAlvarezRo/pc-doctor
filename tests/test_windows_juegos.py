"""Juegos en Windows: catálogo de Steam, Epic, GOG y Xbox, y detección por carpeta de instalación o pantalla completa.
Las rutas son de Windows pero las pruebas corren en Linux (ntpath)."""

from plataforma import windows_juegos as wj

VDF = '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n}\n'


def manifiesto(appid, nombre, carpeta):
    return f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{nombre}"\n\t"installdir"\t\t"{carpeta}"\n}}\n'


EPIC = '{"DisplayName": "Fortnite", "InstallLocation": "E:\\\\Epic Games\\\\Fortnite", "LaunchExecutable": "FortniteLauncher.exe"}'
STEAM_LIB = "d:\\steamlibrary\\steamapps"


def juegos():
    return wj.catalogo({STEAM_LIB: [manifiesto(3321460, "Crimson Desert", "Crimson Desert"), manifiesto(1493710, "Proton Experimental", "Proton - Experimental"),
                                     manifiesto(646570, "Slay the Spire", "SlayTheSpire")]},
                       [EPIC, "no es json"], [{"nombre": "The Witcher 3", "ruta": "C:\\GOG Games\\Witcher 3"}], ["C:\\XboxGames\\Forza Horizon 5"])


def proc(pid, exe, desde=1000):
    return {"pid": pid, "nombre": exe.replace("\\", "/").split("/")[-1], "exe": exe, "desde": desde}


def test_se_leen_las_bibliotecas_de_steam_con_las_barras_duplicadas():
    assert wj.parsear_bibliotecas_steam(VDF) == ["C:\\Program Files (x86)\\Steam", "D:\\SteamLibrary"]


def test_el_manifiesto_de_steam_descarta_herramientas_e_incompletos():
    assert wj.parsear_appmanifest(manifiesto(1, "Slay the Spire", "SlayTheSpire")) == {"appid": "1", "nombre": "Slay the Spire", "carpeta": "SlayTheSpire"}
    assert wj.parsear_appmanifest(manifiesto(2, "Proton 9", "Proton 9.0")) is None and wj.parsear_appmanifest('"AppState" { }') is None


def test_epic_lee_el_json_y_lo_roto_no_rompe():
    assert wj.parsear_epic(EPIC) == {"nombre": "Fortnite", "ruta": "E:\\Epic Games\\Fortnite"}
    assert wj.parsear_epic("{") is None and wj.parsear_epic('{"DisplayName": "x"}') is None and wj.parsear_epic("[]") is None


def test_el_juego_se_reconoce_por_su_carpeta_de_instalacion_en_cada_launcher():
    j = juegos()
    assert wj.juego_de("D:\\SteamLibrary\\steamapps\\common\\Crimson Desert\\bin64\\CrimsonDesert.exe", j) == "Crimson Desert"
    assert wj.juego_de("d:/steamlibrary/steamapps/common/slaythespire/SlayTheSpire.exe", j) == "Slay the Spire"   # sin importar mayúsculas ni barras
    assert wj.juego_de("E:\\Epic Games\\Fortnite\\FortniteGame\\Binaries\\Win64\\FortniteClient-Win64-Shipping.exe", j) == "Fortnite"
    assert wj.juego_de("C:\\GOG Games\\Witcher 3\\bin\\witcher3.exe", j) == "The Witcher 3"
    assert wj.juego_de("C:\\XboxGames\\Forza Horizon 5\\Content\\ForzaHorizon5.exe", j) == "Forza Horizon 5"


def test_un_juego_de_la_biblioteca_sin_manifiesto_se_reconoce_por_su_carpeta_y_las_herramientas_no():
    j = juegos()
    assert wj.juego_de("D:\\SteamLibrary\\steamapps\\common\\Otro Juego\\otro.exe", j) == "otro juego"
    assert wj.juego_de("D:\\SteamLibrary\\steamapps\\common\\Proton - Experimental\\proton.exe", j) is None
    assert wj.juego_de("D:\\SteamLibrary\\steamapps\\common\\Steamworks Shared\\x.exe", j) is None


def test_el_cliente_del_launcher_y_los_auxiliares_no_cuentan_como_juego():
    j = juegos()
    for exe in ("C:\\Program Files (x86)\\Steam\\steam.exe", "C:\\Program Files (x86)\\Steam\\bin\\cef\\steamwebhelper.exe",
                "C:\\Program Files (x86)\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe",
                "D:\\SteamLibrary\\steamapps\\common\\Crimson Desert\\UnityCrashHandler64.exe",
                "D:\\SteamLibrary\\steamapps\\common\\Crimson Desert\\_CommonRedist\\vcredist\\vc_redist.x64.exe",
                "D:\\SteamLibrary\\steamapps\\common\\Crimson Desert\\Launcher.exe", "C:\\Windows\\System32\\svchost.exe", "", None):
        assert wj.juego_de(exe, j) is None, exe


def test_se_informa_un_juego_por_nombre_con_la_hora_del_proceso_mas_antiguo():
    procesos = {1: proc(1, "D:\\SteamLibrary\\steamapps\\common\\SlayTheSpire\\SlayTheSpire.exe", 2000),
                2: proc(2, "D:\\SteamLibrary\\steamapps\\common\\SlayTheSpire\\jre\\bin\\java.exe", 1500),
                3: proc(3, "C:\\Program Files (x86)\\Steam\\steam.exe", 10), 4: proc(4, "C:\\Windows\\explorer.exe", 5)}
    assert wj.identificar(procesos, juegos()) == [{"tipo": "juego", "detalle": "Slay the Spire", "desde": 1500, "firma": "carpeta_de_juego", "pid": 1}]
    assert wj.identificar({}, juegos()) == [] and wj.identificar(procesos, []) == []


# ---------- genérico: pantalla completa + GPU alta ----------

MONITOR = (0, 0, 1920, 1080)
PROCESOS = {10: {"pid": 10, "nombre": "MiJuego.exe", "exe": "X:\\mi\\MiJuego.exe", "desde": 500}, 11: {"pid": 11, "nombre": "chrome.exe", "exe": "C:\\c\\chrome.exe", "desde": 400},
            12: {"pid": 12, "nombre": "steam.exe", "exe": "C:\\s\\steam.exe", "desde": 300}}


def ventana(pid, rect=MONITOR):
    return {"pid": pid, "rect": rect, "monitor": MONITOR}


def test_pantalla_completa_tolera_bordes_de_dos_pixeles():
    assert wj.es_pantalla_completa(ventana(1)) and wj.es_pantalla_completa(ventana(1, (-1, -1, 1921, 1081)))
    assert not wj.es_pantalla_completa(ventana(1, (0, 0, 1280, 720))) and not wj.es_pantalla_completa(None)


def test_un_juego_generico_necesita_pantalla_completa_y_gpu_alta():
    r = wj.juego_generico(ventana(10), {10: 85.0}, PROCESOS)
    assert r == {"tipo": "juego", "detalle": "MiJuego", "desde": 500, "firma": "pantalla_completa", "pid": 10}
    assert wj.juego_generico(ventana(10), {10: 10.0}, PROCESOS) is None                    # a pantalla completa pero sin usar la GPU
    assert wj.juego_generico(ventana(10, (0, 0, 800, 600)), {10: 90.0}, PROCESOS) is None  # usa GPU pero en ventana
    assert wj.juego_generico(ventana(99), {99: 90.0}, PROCESOS) is None                    # proceso que no se puede leer


def test_un_navegador_o_un_cliente_a_pantalla_completa_no_es_un_juego():
    assert wj.juego_generico(ventana(11), {11: 90.0}, PROCESOS) is None
    assert wj.juego_generico(ventana(12), {12: 90.0}, PROCESOS) is None


def test_detectar_arma_todo_con_lecturas_falsas(monkeypatch):
    monkeypatch.setattr(wj, "_leer_catalogo", juegos)
    monkeypatch.setattr(wj, "_procesos", lambda: {1: proc(1, "D:\\SteamLibrary\\steamapps\\common\\SlayTheSpire\\SlayTheSpire.exe", 2000)})
    assert [d["detalle"] for d in wj.detectar({})] == ["Slay the Spire"]
    monkeypatch.setattr(wj, "_procesos", lambda: PROCESOS)
    monkeypatch.setattr(wj, "_ventana_primer_plano", lambda: ventana(10))
    motores = [{"Name": "pid_10_luid_0x0_0x1_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 80}]
    assert [d["detalle"] for d in wj.detectar({"motores_gpu": motores})] == ["MiJuego"]
    assert wj.detectar({}) == []   # sin datos de GPU no se puede afirmar
