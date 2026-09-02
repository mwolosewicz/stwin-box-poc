# STWIN.box – narzędzia do PoC

Zestaw skryptów do pracy z płytką **STEVAL-STWINBX1** (STWIN.box) z firmware'em
**FP-SNS-DATALOG2**, przez USB, bez karty SD i bez telefonu.

Cel: móc w jednej komendzie nagrać drgania maszyny, w drugiej zobaczyć widmo,
a w trzeciej porównać stan sprawny z uszkodzonym.

## Instalacja

```bash
git clone <adres-tego-repo> ~/git/stwin-box-poc
cd ~/git/stwin-box-poc
./setup.sh
```

`setup.sh` klonuje SDK ST, pobiera jego submoduły, tworzy izolowane środowisko
na Pythonie 3.12 i instaluje wszystko, co potrzebne. Można go uruchamiać
wielokrotnie. Zajmuje ok. 2–3 minut przy pierwszym uruchomieniu.

Potem podłącz płytkę kablem USB-C (musi obsługiwać dane, nie tylko ładowanie) i:

```bash
./stwin probe
```

## Użycie

### Sprawdzenie płytki

```bash
./stwin probe            # firmware, lista czujników, do czego który służy
./stwin probe --json     # pełny status urządzenia
```

### Nagrywanie

```bash
./stwin record tlo_biurko --duration 6
./stwin record wentylator_sprawny --duration 20
./stwin record wentylator_niewywazony --duration 20 --opis "plastelina 2 g na łopatce"
./stwin record pralka --sensor ism330dhcx_acc --duration 600
```

Nagranie ląduje w `nagrania/<nazwa>_<data>/` jako komplet plików HSDatalog:
surowe `.dat`, `device_config.json` i `acquisition_info.json`. Domyślnie
nagrywany jest `iis3dwb_acc`, a pozostałe czujniki są wyłączane, żeby nie
mieszać strumieni o bardzo różnych częstotliwościach.

### Analiza

```bash
./stwin analyze nagrania/wentylator_sprawny_20260901_204512
./stwin analyze nagrania/wentylator_sprawny_20260901_204512 --rpm 2400 --fmax 300
```

Zapisuje `widmo.png` w katalogu nagrania: przebieg czasowy, widmo amplitudowe
w pełnym paśmie i PSD w zakresie niskich częstotliwości. `--rpm` dorysowuje
znaczniki 1x, 2x, 3x częstotliwości obrotowej — niewyważenie siedzi przy 1x.

### Porównanie stanu sprawnego z uszkodzonym

```bash
./stwin compare nagrania/wentylator_sprawny_... nagrania/wentylator_niewywazony_... --rpm 2400
```

Nakłada oba widma i rysuje ich stosunek. Wypisuje, przy której częstotliwości
wzrost jest największy i ile wynosi. To jest najszybszy sposób sprawdzenia, czy
uszkodzenie w ogóle jest widoczne — zanim zacznie się budować model.

Szczyt jest szukany na krzywej wygładzonej (`--smooth`, domyślnie 9 prążków),
bo estymator Welcha na samym szumie potrafi dać kilkukrotne skoki
w pojedynczych prążkach. Jeśli wygładzony wzrost nie przekracza 2x, skrypt
mówi wprost, że klasy nie są rozdzielone.

### Wi-Fi i serwer FTP

Firmware ma wbudowany serwer FTP udostępniający zawartość karty SD. Konfiguruje
się go przez USB, bez telefonu:

```bash
./stwin wifi status
./stwin wifi connect --ssid MojaSiec        # zapyta o hasło
./stwin wifi ftp --user maciej              # zapyta o hasło
./stwin wifi disconnect
```

Pominięcie `--password` powoduje pytanie interaktywne, żeby hasło nie zostawało
w historii powłoki. Po udanym połączeniu skrypt wypisuje adres, pod którym
płytka wystawia FTP.

To jest jedyny sposób zdjęcia danych z karty bez wyjmowania jej z płytki —
przez USB się nie da, firmware nie zgłasza się jako pamięć masowa. Przydaje się
przy węźle zamontowanym na stałe przy maszynie.

#### Co przeżywa restart, a co nie

**Hasła nie da się zapisać na płytce.** W kodzie DATALOG2 (`app_netxduo.c`)
`wifi_password` i `ftp_password` to zwykłe tablice znaków w RAM, zerowane przy
każdym starcie. Nie ma żadnego zapisu do flasha ani do modułu Wi-Fi. Po każdym
resecie trzeba je wysłać ponownie — inaczej się nie da bez modyfikacji firmware'u.

Dlatego hasło trzymamy po stronie komputera, w pęku kluczy macOS:

```bash
./stwin wifi connect --ssid MojaSiec --zapamietaj   # raz, przy pierwszym połączeniu
./stwin wifi connect --ssid MojaSiec                # potem już bez pytania
./stwin wifi zapomnij --ssid MojaSiec               # usunięcie wpisu
```

**SSID, nazwa użytkownika FTP i konfiguracja czujników już przeżywają restart**,
o ile zapiszesz je na kartę:

```bash
./stwin wifi save
```

To wywołuje firmware'owe `save_config`, które zapisuje `device_config.json`
w katalogu głównym karty SD; przy starcie płytka ten plik wczytuje. Zapisuje się
komplet ustawień czujników — włączone kanały, ODR, zakresy — więc przydaje się
też poza kontekstem Wi-Fi, do przygotowania płytki na nagrania w terenie.

> **Uwaga.** `save_config` bez włożonej karty potrafi zawiesić firmware na próbie
> montowania i wtedy pomaga wyłącznie przycisk RESET. Skrypt sprawdza
> `sd_mounted` i odmawia, jeśli karty nie ma.

#### Anonimowy FTP

Nie trzeba go włączać — to jest stan domyślny. Firmware startuje z
`ftp_username = "anonymous"` i pustym hasłem, a kontrola dostępu to zwykłe
porównanie obu pól. Logujesz się jako `anonymous` z pustym hasłem i działa.

Adresu IP nie da się ustawić z płytki — właściwość `ip` jest tylko do odczytu,
adres przychodzi z DHCP. Żeby mieć stały adres, zrób na routerze rezerwację
DHCP po adresie MAC modułu Wi-Fi. Uwaga: MAC pokazywany przez `./stwin probe`
należy do modułu Bluetooth, nie Wi-Fi — ten drugi zobaczysz na routerze po
pierwszym udanym połączeniu.

Trzy warunki, o które łatwo się potknąć:

- **Firmware modułu EMW3080 musi być zaktualizowany.** Dokumentacja ST podaje
  to jako wymóg działania DATALOG2 na STWIN.box. Plik binarny jest w paczce
  FP-SNS-DATALOG2, w `Utilities/WiFi_module_upgrade`. Bez tego połączenie nie
  dojdzie do skutku i skrypt o tym przypomni.
- **Tylko 2,4 GHz** — moduł nie obsługuje pasma 5 GHz.
- **Karta SD musi być włożona**, bo FTP serwuje właśnie jej zawartość.

### Eksport do NanoEdge AI Studio

```bash
./stwin nanoedge nagrania/wentylator_sprawny_... -sl 1024 -o dataset/normalne
./stwin nanoedge nagrania/wentylator_niewywazony_... -sl 1024 -o dataset/anomalie
```

`-sl` to długość okna w próbkach; musi być taka sama dla obu klas i taka sama
jak w konfiguracji na urządzeniu. Wywołuje oryginalny konwerter ST, więc
przyjmuje wszystkie jego opcje (`-h` pokaże pełną listę).

## Wybór czujnika

Płytka ma dziewięć czujników i jeden z nich zwykle jest oczywistym wyborem.

| Zadanie | Czujnik | Uwagi |
|---|---|---|
| Drgania maszyn, łożyska | `iis3dwb_acc` | 26,7 kHz, pasmo do 6 kHz, 75 µg/√Hz |
| Długie nagrania (godziny) | `ism330dhcx_acc` | 18 MB/h zamiast 570 MB/h |
| Wycieki sprężonego powietrza | `imp23absu_mic` | pasmo do 80 kHz, ultradźwięki 25–45 kHz |
| Przepływ wody, zdarzenia dźwiękowe | `imp34dt05_mic` | pasmo słyszalne |
| Przechylenia, bardzo niskie f | `iis2iclx_acc` | ±0,5 g, 15 µg/√Hz |
| Wykrycie pracy silnika | `iis2mdc_mag` | pole rozproszone, darmowy sygnał „urządzenie pobiera prąd" |
| Czuwanie na baterii | `iis2dlpc_acc` | kilka µA, wybudzanie po progu |

## Rzeczy, które zaskakują

**Rzeczywiste ODR odbiega od katalogowego.** IIS3DWB przy nominalnych 26 667 Hz
próbkuje realnie ok. 26 316 Hz. Przy 5 kHz to błąd 66 Hz, wystarczający, żeby
rozminąć się z częstotliwością łożyskową. Skrypty liczą `fs` ze znaczników
czasu, nie z nominału — jeśli będziesz pisał własną analizę, rób tak samo.

**ODR i FS w modelu urządzenia to indeksy enum, nie herce i nie g.** `odr=0`
dla IIS3DWB oznacza jedyną dostępną wartość, czyli 26 667 Hz.

**Aplikacja ST BLE Sensor pokazuje niepełną listę czujników.** Brakuje w niej
m.in. IIS3DWB, bo 1,3 Mbit/s nie przejdzie przez BLE. Płytka i firmware widzą
komplet — `./stwin probe` to pokazuje.

**Karty SD nie da się odczytać przez USB.** Firmware wystawia interfejs HID
z protokołem PnPL do sterowania i strumieniowania, nie pamięć masową. Dane
z karty zdejmuje się czytnikiem albo serwerem FTP przez Wi-Fi (`./stwin wifi`).
Przy pracy przy biurku najprościej w ogóle nie używać karty i strumieniować po
USB — tak działają te skrypty.

**Montaż decyduje o wyniku bardziej niż model.** Sztywne przykręcenie albo
klej; taśma dwustronna i pianka działają jak filtr dolnoprzepustowy i kasują
pasmo powyżej ok. 1 kHz. Przemontowanie czujnika zmienia sygnaturę na tyle, że
model nauczony przed przeklejeniem będzie zgłaszał fałszywe alarmy — warto mieć
w danych treningowych kilka różnych montaży.

## Struktura

```
setup.sh              instalacja SDK i środowiska
stwin                 wejście do wszystkich narzędzi
scripts/_common.py    połączenie, wczytywanie nagrań, widma, wykresy
scripts/probe.py      stan płytki i lista czujników
scripts/record.py     akwizycja przez USB
scripts/analyze.py    przebieg czasowy, widmo, PSD
scripts/compare.py    porównanie dwóch nagrań
scripts/wifi.py       konfiguracja Wi-Fi i serwera FTP
nagrania/             wyniki akwizycji (poza repozytorium)
vendor/               SDK ST (poza repozytorium, pobierane przez setup.sh)
docs/plan-poc.md      plan proof of concept i wnioski z rozpoznania
```

## Diagnostyka

SDK jest bardzo gadatliwe i część jego komunikatów to zwykłe `print()`
sformatowane tak, żeby wyglądały jak wpisy loggera — dlatego skrypty filtrują
wyjście. Jeśli coś nie działa i chcesz zobaczyć wszystko:

```bash
STWIN_DEBUG=1 ./stwin probe
```

Gdy płytka nie jest znajdowana: sprawdź, czy kabel USB-C przesyła dane i czy nie
trzyma urządzenia inny program (GUI SDK, ST BLE Sensor przez USB).

Jeśli skrypty mówią, że płytka jest widoczna na USB, ale nie odpowiada na
komendy — firmware się zawiesił. Zdarza się to po przerwanej operacji na karcie
SD. Pomaga wyłącznie przycisk RESET; odłączenie samego USB nie wystarczy, gdy
podpięta jest bateria. SDK w takiej sytuacji po cichu przełącza się na backend
szeregowy i wywala się dopiero przy pierwszej komendzie, dlatego skrypty
sprawdzają łączność od razu po połączeniu i mówią wprost, co zrobić.

## Wymagania

macOS lub Linux, `git`, `curl`. `uv` i Python 3.12 instalują się same przez
`setup.sh`. Płytka musi mieć wgrany FP-SNS-DATALOG2 — sprawdzone z wersją 3.3.0.
