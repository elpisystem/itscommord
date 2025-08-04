#!/bin/bash
set -e
cd ITSCOMMORDSISA
pyinstaller --onefile --windowed --icon="logo.ico" \
--add-data "ftp_itscommconfig.xml:." \
--add-data "logo.png:." \
--add-data "logo.ico:." \
itscomm_main.py
