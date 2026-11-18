# The Bed Leveler 5000 Utility Suite
## The future of FDM bed leveling!

**Bed Leveler 5000** provides a simple method for paper and feeler gauge-free manual
FDB bed leveling. No firmware, setting, configuration, or hardware changes are required
to use **Bed Leveler 5000**.

## Features

- Paper and feeler gauge-free bed leveling
- No printer modifications or extra hardware required
- 3D bed mesh visualiations
- Does not lose, corrupt, or change existing mesh(es) on the printer
- Utility for adding new printer support
- Utility for testing and exploring G-code commands

## Community build (-QS)

This fork ([QuikSilver156/BedLeveler5000][fork]) is a community build by QuikSilver, built with Claude AI.
Releases are tagged `vX.Y.Z` and show as `vX.Y.Z-QS` in **Help > About**. Everything above still applies;
these features are added on top.

### Connecting
- **Native-USB boards work**: DTR is asserted for boards with built-in USB (e.g. Creality 4.2.x / STM32
  "USB Serial Device"), which only answer when it is set. CH340/FTDI/CP210x boards are left alone so they don't reset.
- **Auto-detect printer** (Ports menu): asks each serial port for `M115` at common baud rates and picks the printer,
  so modems and other COM devices aren't mistaken for it.
- **Clear connection errors** instead of raw serial-port codes.
- **Connect through OctoPrint**: level a printer that OctoPrint owns, over its REST API and push socket, without
  unplugging USB. Includes diagnostics and automatic retry when OctoPrint's proxy times out (HTTP 408).
- **Create the mesh when none exists**: after a firmware flash or settings reset, offers to heat the bed, home,
  run `G29` and save (`M500`), then finishes connecting.

### Leveling
- **Plain-English instructions**: "Turn 13 min CCW to lower it" (minutes on a clock face, 15 min = a quarter turn),
  or "At goal, leave it".
- **Readouts aim for 0.000**: every point shows how far it is from the reference, with a ✓ when it is within
  ±0.02 mm; the raw probe height stays alongside.
- **Live adjust**: re-probes one knob over and over while you turn it, so you watch it count down to 0. Steps through
  the knobs 1, 2, 3, ... with **Next point**, re-measures the reference first, and warns before adjustments over 1 mm.
- **Knob-aware**: points without a knob (like a center check point) are never used as the reference or given a turn,
  and fixed supports are respected.
- **Bowed-bed warning** when the corners agree but the middle doesn't, since turning knobs can't fix a bow.
- **Probe averaging**: probe each point 1, 2, 3 or 5 times and see the spread between samples.
- **Heat soak**: wait 2 to 15 minutes after the bed reaches temperature so it has finished expanding.
- **Probe history**: every Probe all is saved to CSV, compared with the last run ("change since last run"),
  and can be exported from the File menu.
- Reference, direction and output style are remembered per printer.

### Watching
- **Webcam**: shows OctoPrint's cameras (classic webcam, OctoPrint 1.9+ webcams and MultiCam) while you probe.
- **Temperature graph** of bed and hotend.
- Camera, temperature controls and graph sit side by side in the main window (resizable), or in their own docks.

### Safety
- Won't start while the printer is printing from SD card, or (through OctoPrint) while OctoPrint reports a job running; stops if a job starts mid-way.
- Asks before quitting while a probe or adjustment is still running.
- Offers to turn the heaters off when you disconnect or close the app.

## Documentation
- **Bed Leveler 5000** Windows install video: [Bed Leveler 5000 Windows installation][BedLeveler5000WindowsInstallVideo]
- **Bed Leveler 5000** Klipper support video: [Bed Leveler 5000 Klipper support][BedLeveler5000KlipperVideo]
- **Bed Leveler 5000** introduction video: [Bed Leveler 5000][BedLeveler5000Video]
- **Printer Info Wizard** Klipper support video: [Printer Info Wizard Klipper support][PrinterInfoWizardKlipperVideo]
- **Printer Info Wizard** introduction video: [Printer Info Wizard][PrinterInfoWizardVideo]
- **Inspector G-code** introduction video: [Inspector G-code][InspectorG-code]
- Homepage: https://sandmmakers.com/Projects/BedLeveler5000

## Tech

**Bed Leveler 5000** uses a number of open source projects to work properly:

- [PySide6] - The official Python module from the Qt for Python project
- [Python] - The Python programming language (3.12+)
- [pylint] - A static code analyser for Python 2 and 3
- [Pillow] - The friendly PIL fork
- [GnuPG] - A free implementation of the OpenPGP standard

[Bed Leveler 5000][BedLeveler5000], [Printer Info Wizard][BedLeveler5000], and [Inspector G-code][InspectorG-code] themselves are open source with a [public repository][bedleveler5000] on GitHub.

## Installation
>[!NOTE]
> In the following directions, replace `vX.X.X` with the desired version of Bed Leveler 5000.
### Windows
1) Download the **BedLeveler5000-vX.X.X-windows-x86_64.7z** file from the latest release at https://github.com/QuikSilver156/BedLeveler5000/releases (community build) or https://github.com/sandmmakers/BedLeveler5000/releases (original)
2) Extract the downloaded archive
3) Launch **BedLeveler5000.exe**, **PrinterInfoWizard.exe**, or **InspectorG-code.exe**

### Ubuntu Linux
>[!NOTE]
>Use of Ubuntu's Dark theme is not recommended.

1) Configure the system
    1) Ensure **brltty** is not installed
       ```
       sudo apt remove brltty
       ```
    2) Give the current user permissions to use serial ports
       ```
       sudo usermod -a -G dialout $USER
       ```
    3) Reboot to ensure all changes take effect
2) Download the **BedLeveler5000-vX.X.X-linux-x86_64.tgz** file from the latest release at https://github.com/QuikSilver156/BedLeveler5000/releases (community build) or https://github.com/sandmmakers/BedLeveler5000/releases (original)
3) Extract the downloaded archive
4) Launch **BedLeveler5000**, **PrinterInfoWizard**, or **InspectorG-code**

### MacOS
1) Give the current user permissions to use serial ports
   ```
   sudo dseditgroup -o edit -a "$(whoami)" -t user "wheel"
   ```
2) Reboot to ensure changes take effect
3) Download the **BedLeveler5000-vX.X.X-macos-x86_64.tgz** file from the latest release at https://github.com/QuikSilver156/BedLeveler5000/releases (community build) or https://github.com/sandmmakers/BedLeveler5000/releases (original)
4) Open a terminal
5) Extract archive
   ```
   tar xvf BedLeveler5000-vX.X.X-macos-x86_64.tgz
   ```
6) Enter directory
   ```
   cd BedLeveler5000-vX.X.X-macos-x86_64
   ```
7) Add execute permissions
   ```
   chmod +x BedLeveler5000 PrinterInfoWizard InspectorG-code PrinterTester
   ```
8) Disable quarantine as the applications are unsigned
   ```
   xattr -d com.apple.quarantine -r .
   ```
9) Run desired application
    - Bed Leveler 5000
      ```
      ./BedLeveler5000
      ```

    - Printer Info Wizard
      ```
      ./PrinterInfoWizard
      ```
    - Inspector G-code
      ```
      ./InspectorG-code
      ```

## Release integrity
Starting with version **v0.4.0**, original releases are cryptographically signed with the GPG key [03E565C3F0C71CB2] and are fully automated.
Community (-QS) releases are built automatically by GitHub Actions from this repository but are not GPG-signed.

## Filing a bug report
See [Filing a bug report](Docs/FilingABugReport.md). For problems with a -QS build, mention the -QS version from Help > About.

## Building from source
See [Building from source](Docs/BuildingFromSource.md)

## License

GPLv3

   [BedLeveler5000]: <https://sandmmakers.com/Projects/BedLeveler5000>
   [fork]: <https://github.com/QuikSilver156/BedLeveler5000>
   [git-repo-url]: <https://github.com/sandmmakers/BedLeveler5000.git>
   [BedLeveler5000WindowsInstallVideo]: <https://youtu.be/QwbeFVCBk6Q>
   [BedLeveler5000KlipperVideo]: <https://youtu.be/JBGN3U0C2LM>
   [BedLeveler5000Video]: <https://youtu.be/j5rzlHdtJAo>
   [PrinterInfoWizardKlipperVideo]: <https://youtu.be/VC4FoqCr5-g>
   [PrinterInfoWizardVideo]: <https://youtu.be/vVYRg6_kZsc>
   [InspectorG-code]: <https://youtu.be/EVntFYltG1U>
   [PySide6]: <https://pypi.org/project/PySide6>
   [Python]: <https://www.python.org>
   [pylint]: <https://github.com/pylint-dev/pylint>
   [Pillow]: <https://github.com/python-pillow/Pillow>
   [GnuPG]: <https://www.gnupg.org>
   [03E565C3F0C71CB2]: <https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x0A55C210C62C5A0AE461C36503E565C3F0C71CB2>