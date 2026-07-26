# -*- coding: utf-8 -*-
# IFD-2 : firmware Pico (MicroPython) pour piloter la Xerox 575 (TA SE, protocole IFD1).
# ------------------------------------------------------------------------------------
# NON TESTE : ossature a calibrer au bring-up (polarites DSR, timing flux) — repere "TODO".
#
# Cablage (voir plan) :
#   GP0 (UART0 TX) --1k--> vert-blanc (RX machine)
#   GP1 (UART0 RX) <-diviseur 1k/2k- orange (TX machine, 5V)
#   GP2 (sortie)   --1k--> bleu (DSR : reset + hote present)
#   GP3 (entree)   <-diviseur 1k/2k- vert (DTR : flux)
#   GND <-> marron.   Pico alimente par USB. Jamais B/E.
#
# Usage : copier ce fichier en main.py sur le Pico (MicroPython). Il attend du texte
# ligne par ligne sur l'USB (stdin) et l'imprime. Fonctions testables depuis le REPL.

from machine import UART, Pin
import sys
import time

# ------------------------------------------------------------------ config / IO
UART_ID, TX_PIN, RX_PIN = 0, 0, 1
DSR_PIN, DTR_PIN = 2, 3
GAP_MS = 800          # v1 : temps pur (comme sur Mac). A reduire avec le flux GP3 (v2).
FORCE = 40            # force de frappe 0-63

# RX : UART materiel sur GP1. TX materiel deporte sur GP12 (NON CONNECTE, inutilise) :
# on emet en logiciel sur GP0 en OPEN-DRAIN, seule facon d'obtenir un vrai niveau
# haut a 5 V (le Pico relache, le pull-up 4k de la machine fait le travail).
# Necessaire car l'entree de la machine est CMOS (seuil ~3,5 V) et une sortie
# push-pull 3,3 V n'y suffit pas.
uart = UART(UART_ID, baudrate=4800, bits=8, parity=None, stop=1,
            tx=Pin(12), rx=Pin(RX_PIN), timeout=50)
tx = Pin(TX_PIN, Pin.OPEN_DRAIN, value=1)   # GP0 : 1 = relache (5 V), 0 = tire a la masse
BIT_US = 208                                 # 1/4800 s = 208,33 us

def _tx(data):
    """Emission logicielle 8N1 sur GP0 (open-drain), avec echeances cumulees
    pour eviter toute derive de timing."""
    for b in bytes(data):
        bits = [0] + [(b >> i) & 1 for i in range(8)] + [1]   # start, LSB..MSB, stop
        t0 = time.ticks_us()
        for k, v in enumerate(bits):
            tx.value(v)
            target = time.ticks_add(t0, (k + 1) * BIT_US)
            while time.ticks_diff(target, time.ticks_us()) > 0:
                pass
        tx.value(1)
# DSR en OPEN-DRAIN comme la ligne de donnees : le niveau haut est alors fourni
# par le pull-up 5 V de la machine (et non par les 3,3 V du Pico, insuffisants
# pour une entree CMOS a seuil 3,5 V). value=0 => tire a la masse = asserte.
dsr = Pin(DSR_PIN, Pin.OPEN_DRAIN, value=0)
dtr = Pin(DTR_PIN, Pin.IN)

# ------------------------------------------------------------------ table roue FR
WHEEL = list('.,-vlmjw²μf¥>¶+1234567890E£BFPSZV&YATL$R*C"D?NIU)'
             'W_=;:M\'H(K/O!X§QJ%³G°¼¢½<Δ#txqΩ]@['
             'ykphcgnrseaiduboz')
# substitutions FR relevees (index 1-based)
for _i, _c in {12: '^', 13: 'è', 14: 'é', 72: 'ì', 74: '¨',
               75: '◊', 80: 'ç', 81: 'ù', 82: 'ò', 83: 'à'}.items():
    WHEEL[_i - 1] = _c
IDX_OF = {c: n + 1 for n, c in enumerate(WHEEL)}

col = 0   # position chariot (pas), pour le retour a la ligne exact

# ------------------------------------------------------------------ bas niveau
def _flush_in():
    while uart.any():
        uart.read()

def reset_pulse(invert=False):
    """Impulsion de reset sur DSR.

    Raisonnement polarite : cote FT232, la ligne RTS# est ACTIVE BASSE.
    pyserial faisait  rts=True (broche a 0V, repos)  puis  rts=False (3-5V)
    puis rts=True (retour 0V). Donc : repos = BAS, impulsion = breve HAUTE.
    C'est ce qu'on reproduit par defaut. invert=True pour tester l'inverse.
    """
    idle, act = (1, 0) if invert else (0, 1)
    dsr.value(idle)
    time.sleep_ms(2)
    dsr.value(act)
    time.sleep_ms(3)
    dsr.value(idle)      # on reste asserte au repos = "hote present"

def connect(attempts=15, invert=False):
    """Repete l'impulsion de reset jusqu'a recevoir 0x01."""
    for n in range(attempts):
        _flush_in()
        reset_pulse(invert)
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 1000:
            if uart.any():
                b = uart.read(1)
                if b == b'\x01':
                    print("0x01 recu (tentative %d)" % (n + 1))
                    return True
                elif b:
                    print("  recu %s" % b.hex())
        time.sleep_ms(100)
    return False

USE_FLOW = True     # True = contrôle de flux par l'accusé DTR (rapide). False = délai fixe.

def send_byte(b, timeout_ms=4000):
    """Envoie UN octet puis attend l'accuse de reception de la machine :
    DTR (GP3) monte a 1 pendant ~1 ms => 'octet recu, envoie le suivant'.
    Quand le buffer machine est plein, cet accuse est RETARDE le temps qu'un
    caractere soit frappe : la machine impose donc elle-meme son rythme."""
    # 1) s'assurer que DTR est au repos (bas) AVANT d'ecrire, sinon un reste
    #    d'impulsion serait pris pour l'accuse du nouvel octet (fausse detection).
    t0 = time.ticks_ms()
    while dtr.value() == 1:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            break
    # 2) emettre
    _tx([b])
    # 3) attendre le front montant = accuse
    t0 = time.ticks_ms()
    while dtr.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
            return False
    # 4) laisser l'impulsion se terminer
    t1 = time.ticks_ms()
    while dtr.value() == 1:
        if time.ticks_diff(time.ticks_ms(), t1) > 500:
            break
    return True

def send_pair(b1, b2, flow=None, timeout_ms=4000):
    """flow=None -> USE_FLOW. flow=False force le delai fixe (init : la machine
    n'emet PAS d'accuse DTR tant qu'elle n'est pas online).
    timeout_ms : a rallonger pour les commandes mecaniques longues (retour chariot)."""
    if flow is None:
        flow = USE_FLOW
    if flow:
        # /!\ JAMAIS de court-circuit ici : les DEUX octets doivent partir, sinon
        # la machine recoit un nombre impair d'octets -> desynchronisation totale.
        ok1 = send_byte(b1, timeout_ms)
        ok2 = send_byte(b2, timeout_ms)
        if not (ok1 and ok2):
            print("!! accuse DTR manquant (paire quand meme envoyee)")
            time.sleep_ms(GAP_MS)
    else:
        _tx([b1, b2])
        time.sleep_ms(GAP_MS)

INIT_GAP_MS = 300   # valeur de la version de reference (fiable)

def online(retries=4):
    """VERSION DE REFERENCE (celle qui etait fiable) : envoie l'init et verifie
    l'echo global de 0xA2. Pas de fermeture prealable (A3 bloque la machine),
    pas de renvoi commande par commande (ce sont des transitions d'etat)."""
    for attempt in range(1, retries + 1):
        _flush_in()
        for b1, b2 in ((0xA0, 0), (0xA1, 0), (0xA4, 0), (0xA2, 0)):
            _tx([b1, b2])
            time.sleep_ms(INIT_GAP_MS)
        time.sleep_ms(400)
        echo = uart.read() or b''
        if 0xA2 in echo:
            print("online confirme (echo : %s)" % echo.hex(' '))
            time.sleep_ms(500)
            _tx([0x82, 0x0F])            # reset position
            time.sleep_ms(2000)          # calage chariot
            _tx([0x80, PITCH])           # pas d'ecriture
            time.sleep_ms(300)
            return True
        print("  tentative %d : pas d'echo A2 (recu : %s)"
              % (attempt, echo.hex(' ') if echo else 'rien'))
        time.sleep_ms(300)
    return False

def step(b1, b2, wait_ms=1200):
    """Envoie UNE paire et affiche ce que la machine renvoie. Pour derouler
    l'init a la main, une commande par ligne, et voir ou ca casse."""
    _tx([b1, b2])
    t0 = time.ticks_ms()
    r = b''
    while time.ticks_diff(time.ticks_ms(), t0) < wait_ms:
        if uart.any():
            r += uart.read()
    print("%02X %02X  ->  %s" % (b1, b2, r.hex(' ') if r else 'rien'))
    return r

def window_test(delay_ms=0):
    """Mesure la FENETRE d'acceptation apres le 0x01 : connecte, attend
    delay_ms, puis envoie A0 et regarde si la machine repond.
    Essayer 0, 200, 600, 1500, 3000 pour trouver la limite."""
    if not connect():
        print("pas de 0x01")
        return None
    time.sleep_ms(delay_ms)
    print("delai %d ms :" % delay_ms, end=' ')
    return step(0xA0, 0, wait_ms=900)

def ping(timeout_ms=600):
    """ENQ (A4) = 'es-tu la ?'. La machine repond par un bloc de statut si la
    session est encore ouverte. Sert de battement de coeur : la session expire
    apres un moment d'inactivite."""
    _flush_in()
    _tx([0xA4, 0x00])
    t0 = time.ticks_ms()
    resp = b''
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        if uart.any():
            resp += uart.read()
    return resp

def ensure_ready(verbose=True):
    """Verifie que la session est vivante ; la rouvre sinon.
    A appeler avant tout travail d'impression."""
    r = ping()
    if r:
        return True
    if verbose:
        print("session expiree -> reouverture...")
    return start()

# ------------------------------------------------------------------ impression
def strike(idx):
    global col
    send_pair(idx, 0x80 | (FORCE & 0x3F))
    col += 1

def space():
    global col
    send_pair(0x01, 0x80)      # frappe a blanc
    col += 1

def _wait_idle(quiet_ms=400, timeout_ms=8000):
    """Attend que la machine ait vide son buffer d'impression : on considere
    qu'elle a fini quand DTR n'a plus emis d'accuse depuis quiet_ms."""
    t0 = time.ticks_ms()
    last = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        if dtr.value() == 1:
            last = time.ticks_ms()
        if time.ticks_diff(time.ticks_ms(), last) > quiet_ms:
            return True
    return False

def raw(b1, b2, wait_ms=900):
    """Envoie une paire d'octets brute et attend. Sert a explorer les commandes
    (interligne, deplacements) depuis le REPL : ifd2.raw(0xD0, 0x14)"""
    _wait_idle()
    _tx([b1, b2])
    time.sleep_ms(wait_ms)
    print("envoye %02X %02X" % (b1, b2))

LF_CMD = (0xD0, 0x10)     # interligne (0x14 = trop large, 0x0C = plus serre)

def newline():
    """Retour chariot (commande officielle 0x82, drapeau chariot) + interligne.
    Pas de controle de flux : ces mouvements n'emettent pas d'accuse DTR."""
    global col
    _wait_idle()                      # attendre que le buffer d'impression soit vide
    _tx([0x82, 0x03])                 # 1 (base) + 2 (chariot) = retour au debut de ligne
    time.sleep_ms(1200)
    _tx(list(LF_CMD))                 # interligne
    time.sleep_ms(700)
    col = 0

PITCH = 0x0A          # largeur d'un caractere en unites : 0x0F = normal, 0x0A = condense
LINE_UNITS = 975      # largeur utile de la ligne, en unites (ajuster selon le papier)
LINE_LEN = LINE_UNITS // PITCH     # caracteres par ligne, recalcule par set_pitch()

def set_pitch(p=None):
    """Regle le pas d'ecriture (largeur d'un caractere en unites) et ajuste
    automatiquement le nombre de caracteres par ligne.
    0x0F = normal, 0x0A = condense, valeurs plus petites = chevauchement."""
    global PITCH, LINE_LEN
    if p is None:
        p = PITCH
    _wait_idle()
    _tx([0x80, p])
    time.sleep_ms(300)
    PITCH = p
    LINE_LEN = LINE_UNITS // p
    print("pas = 0x%02X -> %d caracteres par ligne" % (p, LINE_LEN))

def _wrap(text, width):
    """Decoupe le texte en lignes <= width, en cassant aux espaces (pas au milieu
    des mots). Les '\\n' du texte sont respectes comme sauts forces."""
    out = []
    for para in text.split('\n'):
        line = ''
        for word in para.split(' '):
            if not word:
                continue
            cand = word if not line else line + ' ' + word
            if len(cand) <= width:
                line = cand
            else:
                if line:
                    out.append(line)
                while len(word) > width:          # mot plus long que la ligne
                    out.append(word[:width])
                    word = word[width:]
                line = word
        out.append(line)
    return out

def print_text(text, wrap=True, end_newline=True, check=True):
    """Imprime du texte. wrap=True : retour a la ligne automatique a LINE_LEN.
    end_newline=True : termine par un retour a la ligne.
    check=True : verifie/rouvre la session avant d'imprimer (elle expire)."""
    if check and not ensure_ready():
        print("impossible d'ouvrir la session — cycle secteur machine.")
        return
    lines = _wrap(text, LINE_LEN) if wrap else text.split('\n')
    last = len(lines) - 1
    for i, ln in enumerate(lines):
        for c in ln:
            if c == ' ':
                space()
            elif c in IDX_OF:
                strike(IDX_OF[c])
            # sinon : caractere absent de la roue -> ignore
        if i < last or end_newline:
            newline()

def offline():
    """Rend la main au clavier de la machine."""
    send_pair(0xA3, 0x00, flow=False)
    send_pair(0xA0, 0x00, flow=False)

def listen(seconds=20):
    """Ecoute la ligne TX de la machine : affiche tout octet recu.
    A tester : appuyer sur ON LINE, taper au clavier, en ligne comme hors ligne."""
    print("ecoute %d s — tape sur le clavier / presse ON LINE..." % seconds)
    t0 = time.ticks_ms()
    got = 0
    while time.ticks_diff(time.ticks_ms(), t0) < seconds * 1000:
        if uart.any():
            b = uart.read(1)
            if b:
                v = b[0]
                print("  0x%02X (%3d) %s" % (v, v, chr(v) if 32 <= v < 127 else '.'))
                got += 1
    print("fini : %d octet(s)" % got)

def start(invert=False):
    """UNE commande pour tout faire : connexion + passage online, avec verifications.
    Evite de coller plusieurs lignes dans le REPL (elles se marchent dessus)."""
    print("connexion...")
    if not connect(invert=invert):
        print("ECHEC : pas de 0x01. -> cycle secteur machine, attendre le chariot, reessayer.")
        return False
    time.sleep_ms(1200)         # MESURE : la machine n'accepte les commandes qu'a
                                # partir de ~1 s apres le 0x01 (600 ms = trop tot,
                                # 3 s = elle repete son 0x01). Voir window_test().
    print("passage online...")
    if not online():
        print("ECHEC : l'init n'a pas ete confirmee. -> cycle secteur machine, Ctrl-D, reessayer.")
        return False
    print("PRET (LED ON LINE allumee).")
    return True


# ------------------------------------------------------------------ mesure du flux (v2)
def probe_dtr(idx=93, ms=1500):
    """Frappe un caractere et journalise TOUTES les transitions de DTR (GP3)
    a la microseconde. C'est ce que le Mac ne pouvait pas faire.
    But : voir la forme reelle du signal 'occupee/prete' pour caler le flux."""
    trans = []
    last = dtr.value()
    print("DTR avant frappe = %d" % last)
    _tx([idx, 0x80 | (FORCE & 0x3F)])
    t0 = time.ticks_us()
    while time.ticks_diff(time.ticks_us(), t0) < ms * 1000:
        v = dtr.value()
        if v != last:
            trans.append((time.ticks_diff(time.ticks_us(), t0), v))
            last = v
            if len(trans) >= 40:
                break
    if not trans:
        print("DTR n'a PAS bouge pendant %d ms" % ms)
    else:
        for t, v in trans:
            print("  t = %8.2f ms   DTR -> %d" % (t / 1000.0, v))
    return trans


def selftest_tx():
    """Verifie que l'emission logicielle produit de vrais octets 8N1.
    CABLAGE TEMPORAIRE : un fil du noeud vert-blanc (ou de GP0) vers GP5 = H7.
    GP5 est l'entree de l'UART1 materiel : il decode ce que GP0 emet."""
    u1 = UART(1, baudrate=4800, bits=8, parity=None, stop=1,
              rx=Pin(5), timeout=300)
    u1.read()
    ref = b'\x55\xA2\x00\x41\xA0'
    _tx(ref)
    time.sleep_ms(300)
    got = u1.read()
    print("emis  :", ref.hex(' ') if hasattr(ref, 'hex') else ref)
    print("relu  :", got.hex(' ') if got else "(rien)")
    print("=> ", "IDENTIQUE, bit-bang OK" if got == ref else "DIFFERENT : timing a corriger")
    return got


def tx_test(byte=0x00, ms=3000):
    """Emet le meme octet en boucle pendant ms. Sert a VERIFIER l'emission
    au multimetre : mesurer la tension MOYENNE sur le fil vert-blanc.
      tx_test(0x00) -> 9 bits bas sur 10 -> moyenne attendue ~0,5-1 V
      tx_test(0xFF) -> 9 bits hauts sur 10 -> moyenne attendue ~4,5 V
    Si la tension ne bouge pas entre les deux, GP0 n'emet pas."""
    print("emission de 0x%02X pendant %d ms — mesure vert-blanc maintenant" % (byte, ms))
    t0 = time.ticks_ms()
    n = 0
    while time.ticks_diff(time.ticks_ms(), t0) < ms:
        _tx([byte])
        n += 1
    print("%d octets emis" % n)


def debug_send(text="abc"):
    """Envoie du texte en journalisant, pour CHAQUE octet, le delai de l'accuse DTR.
    But : voir si les accuses sont reels (delai ~2-4 ms) ou fantomes (0 ms),
    et si la machine ralentit quand son buffer se remplit."""
    print("octet | accuse en | etat DTR avant")
    for c in text:
        if c not in IDX_OF:
            continue
        idx = IDX_OF[c]
        for b in (idx, 0x80 | (FORCE & 0x3F)):
            before = dtr.value()
            t0 = time.ticks_us()
            while dtr.value() == 1:                       # attendre le repos
                if time.ticks_diff(time.ticks_us(), t0) > 500000:
                    break
            _tx([b])
            t1 = time.ticks_us()
            ok = True
            while dtr.value() == 0:                       # attendre l'accuse
                if time.ticks_diff(time.ticks_us(), t1) > 4000000:
                    ok = False
                    break
            dt = time.ticks_diff(time.ticks_us(), t1) / 1000.0
            while dtr.value() == 1:                       # fin d'impulsion
                if time.ticks_diff(time.ticks_us(), t1) > 5000000:
                    break
            print("  0x%02X |  %7.2f ms %s | %d" % (b, dt, "" if ok else "(TIMEOUT)", before))
    print("fini.")


def wait_ready(busy_level=0, timeout_ms=2500):
    """Attend que la machine redevienne PRETE apres un octet.
    busy_level = niveau logique signifiant 'occupee' (a caler avec probe_dtr).
    1) attend l'entree en occupation (max 150 ms), 2) attend la sortie."""
    t0 = time.ticks_ms()
    while dtr.value() != busy_level:                      # entree en occupation
        if time.ticks_diff(time.ticks_ms(), t0) > 150:
            return False                                   # jamais vue -> repli temporel
    t0 = time.ticks_ms()
    while dtr.value() == busy_level:                       # sortie d'occupation
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
            return False
    return True


# ------------------------------------------------------------------ boucle principale
def run():
    print("IFD-2 : connexion a la machine...")
    if not connect():
        print("ECHEC 0x01 -> cycle secteur machine, puis reset Pico.")
        return
    print("connecte. Passage online...")
    online()
    print("PRET. Envoie du texte ligne par ligne (chaque ligne s'imprime).")
    while True:
        line = sys.stdin.readline()
        if not line:
            continue
        print_text(line.rstrip('\n'))
        newline()

if __name__ == "__main__":
    run()
