import os
from ftplib import FTP, error_perm

class FTPHandler:
    def __init__(self, host, user, password, base_dir="/", target_dir="/importati"):
        self.host = host
        self.user = user
        self.password = password
        self.base_dir = base_dir # Directory FTP principale da cui scaricare i file "dati"
        self.target_dir = target_dir # Directory FTP dove spostare i file "dati" processati (es. /importati)
        self.ftp = None
        self.connection_error = None

    def connect(self):
        """Stabilisce la connessione FTP e fa il login."""
        try:
            self.ftp = FTP(self.host, timeout=30)
            self.ftp.login(self.user, self.password)
            # Non cambiare directory qui, fallo prima di operazioni specifiche se necessario
            # if self.base_dir and self.base_dir != "/":
            #     self.ftp.cwd(self.base_dir)
            self.connection_error = None
            return True
        except Exception as e:
            self.ftp = None
            self.connection_error = e
            return False

    def disconnect(self):
        """Chiude la connessione FTP se aperta."""
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception as e:
                print(f"FTPHandler: Errore durante ftp.quit(): {e}")
            finally:
                self.ftp = None

    def get_last_connection_error(self):
        return self.connection_error

    def ensure_ftp_dir_exists(self, directory_path):
        """
        Assicura che una specifica directory FTP esista.
        Se non esiste, tenta di crearla.
        Ritorna (True, messaggio) se successo, (False, messaggio_errore) altrimenti.
        Presuppone che la connessione sia già stabilita.
        """
        if not self.ftp:
            return False, "FTP non connesso."
        if not directory_path:
            return False, "Percorso directory FTP non specificato."

        original_dir = self.ftp.pwd()
        # print(f"DEBUG FTP: CWD corrente '{original_dir}' prima di ensure_ftp_dir_exists per '{directory_path}'")
        try:
            self.ftp.cwd(directory_path)
            # print(f"DEBUG FTP: CWD a '{directory_path}' riuscito (directory esiste).")
            # Se cwd ha successo, la directory esiste. Torniamo alla directory originale per non alterare lo stato.
            if self.ftp.pwd() != original_dir: # Solo se CWD ha effettivamente cambiato directory
                 self.ftp.cwd(original_dir)
            # print(f"DEBUG FTP: Ritornato a CWD originale '{original_dir}'")
            return True, f"Directory FTP '{directory_path}' già esistente o accessibile."
        except error_perm: # La directory probabilmente non esiste (errore 550 comune)
            # print(f"DEBUG FTP: CWD a '{directory_path}' fallito (error_perm). Tentativo MKD.")
            try:
                # MKD crea una directory. Il path può essere relativo o assoluto.
                # Se directory_path è assoluto (es. /foo/bar), funziona indipendentemente dalla CWD.
                # Se è relativo (es. foo/bar), viene creato dentro la CWD.
                # Per sicurezza, se non è un path assoluto, potremmo voler navigare a una base specifica
                # ma per /importati e /DOC_importati, dovrebbero essere percorsi assoluti dalla root FTP.
                self.ftp.mkd(directory_path)
                # print(f"DEBUG FTP: MKD '{directory_path}' riuscito.")
                return True, f"Directory FTP '{directory_path}' creata."
            except Exception as e_mkd:
                # print(f"DEBUG FTP: MKD '{directory_path}' fallito: {e_mkd}")
                # Tentiamo di tornare alla directory originale in ogni caso se possibile
                try:
                    if self.ftp.pwd() != original_dir: self.ftp.cwd(original_dir)
                except: pass
                return False, f"Errore creazione directory '{directory_path}' su FTP: {e_mkd}"
        except Exception as e_general:
            # print(f"DEBUG FTP: Errore generale con '{directory_path}': {e_general}")
            try:
                if self.ftp.pwd() != original_dir: self.ftp.cwd(original_dir)
            except: pass
            return False, f"Errore imprevisto con directory '{directory_path}' su FTP: {e_general}"

    def list_files_in_current_dir(self, only_files=True):
        """
        Lista i file (e opzionalmente le directory) nella directory FTP corrente.
        Utilizza MLSD se disponibile (preferito), altrimenti ricade su NLST.
        Ritorna una lista di nomi, o None e messaggio d'errore.
        Se only_files è True e MLSD è usato, ritorna solo file.
        Se only_files è True e MLSD fallisce (ricadendo su NLST), ritorna tutti gli elementi
        da NLST (eccetto '.' e '..') e stampa un avviso, poiché NLST non distingue tipi.
        """
        if not self.ftp:
            return None, "FTP non connesso."

        item_list = []
        try:
            # MLSD è preferito perché fornisce informazioni sul tipo
            # 'facts=["type"]' richiede solo il tipo, alcuni server potrebbero non supportare altri facts.
            for name, facts in self.ftp.mlsd(facts=["type"]):
                if facts.get("type") == "file":
                    item_list.append(name)
                elif not only_files and facts.get("type") == "dir":
                    if name not in ['.', '..']: # Escludi '.' e '..' per le directory
                        item_list.append(name)
            return item_list, None
        except error_perm as e_mlsd:
            # MLSD potrebbe non essere supportato o l'utente potrebbe non avere i permessi (comune: 500 'MLSD not understood')
            print(f"FTPHandler: MLSD non supportato o fallito ({e_mlsd}), ricaduta su NLST.")
            try:
                nlst_items = self.ftp.nlst()
                # Filtra '.' e '..' da NLST
                filtered_nlst_items = [item for item in nlst_items if item not in ['.', '..']]

                if only_files:
                    # Con NLST, non possiamo distinguere file da directory in modo affidabile a questo livello.
                    # Restituiamo tutti gli elementi filtrati e stampiamo un avviso.
                    # Il chiamante dovrà gestire gli errori se tenta di scaricare una directory.
                    print("FTPHandler: Avviso - Ricaduta su NLST non può filtrare solo file. Tentativi di download su directory potrebbero ancora verificarsi.")
                    return filtered_nlst_items, None
                else:
                    # Se only_files è False, restituiamo tutti gli elementi (comportamento simile a prima per NLST)
                    return filtered_nlst_items, None
            except Exception as e_nlst:
                return None, f"Errore nel listare i file FTP (ricaduta NLST): {e_nlst}"
        except Exception as e_general_mlsd: # Altre eccezioni da MLSD
            return None, f"Errore generale nel listare i file FTP con MLSD: {e_general_mlsd}"

    def change_ftp_dir(self, directory_path):
        """Cambia la directory corrente sull'FTP."""
        if not self.ftp:
            return False, "FTP non connesso."
        try:
            self.ftp.cwd(directory_path)
            return True, f"CWD FTP impostata a: {self.ftp.pwd()}"
        except Exception as e:
            return False, f"Impossibile cambiare CWD FTP a '{directory_path}': {e}"

    def get_current_ftp_dir(self):
        if not self.ftp:
            return None
        try:
            return self.ftp.pwd()
        except Exception:
            return None


    def download_file(self, remote_filename, local_filepath):
        """
        Scarica un singolo file dalla directory FTP corrente.
        Ritorna (True, None) in caso di successo, (False, messaggio_errore) altrimenti.
        """
        if not self.ftp:
            return False, "FTP non connesso."
        try:
            with open(local_filepath, "wb") as f:
                self.ftp.retrbinary(f"RETR {remote_filename}", f.write)
            return True, None
        except Exception as e:
            if os.path.exists(local_filepath):
                try:
                    os.remove(local_filepath)
                except Exception as e_del:
                    print(f"FTPHandler: Impossibile rimuovere file parziale {local_filepath}: {e_del}")
            return False, f"Errore scaricamento {remote_filename}: {e}"

    def move_file_on_ftp(self, source_filename, destination_path):
        """
        Sposta/Rinomina un file sulla directory FTP corrente a un nuovo percorso.
        source_filename: nome del file nella CWD FTP (es. "file.txt").
        destination_path: percorso completo di destinazione sull'FTP (es. "/importati/file.txt").
        Ritorna (True, None) in caso di successo, (False, messaggio_errore) altrimenti.
        """
        if not self.ftp:
            return False, "FTP non connesso."
        try:
            # print(f"DEBUG FTP: Attempting to RENAME '{source_filename}' (from CWD: {self.ftp.pwd()}) TO '{destination_path}'")
            self.ftp.rename(source_filename, destination_path)
            return True, None
        except Exception as e:
            return False, f"Errore spostamento/rinomina FTP da '{source_filename}' a '{destination_path}': {e}"

# Esempio di utilizzo (richiede un server FTP per testare)
if __name__ == '__main__':
    # Queste credenziali sono fittizie, sostituire con reali per testare
    handler = FTPHandler("localhost", "testuser", "testpass", base_dir="/source_files", target_dir="/processed_files")
    # Per testare, crea un server FTP locale con user 'testuser' pass 'testpass'
    # e le directory /source_files, /doc_files. Metti file in source_files e doc_files.

    if handler.connect():
        print(f"Connesso a {handler.host}")

        # Test ensure_ftp_dir_exists
        test_archive_dir = "/processed_files"
        test_doc_archive_dir = "/doc_files_processed"

        ok, msg = handler.ensure_ftp_dir_exists(test_archive_dir)
        print(f"Ensure '{test_archive_dir}': {ok} - {msg}")

        ok, msg = handler.ensure_ftp_dir_exists(test_doc_archive_dir)
        print(f"Ensure '{test_doc_archive_dir}': {ok} - {msg}")

        # Test cambio directory e listaggio
        print(f"\nTest listaggio in base_dir: {handler.base_dir}")
        ok_cwd_base, msg_cwd_base = handler.change_ftp_dir(handler.base_dir)
        if ok_cwd_base:
            print(msg_cwd_base)
            files_base, err_base = handler.list_files_in_current_dir()
            if err_base: print(f"Errore: {err_base}")
            else: print(f"File in {handler.base_dir}: {files_base}")

            # Test download e move
            if files_base and len(files_base) > 0:
                fname_to_test = files_base[0]
                local_dl = f"./{fname_to_test}.downloaded"
                print(f"Tentativo download di {fname_to_test}...")
                ok_dl, msg_dl = handler.download_file(fname_to_test, local_dl)
                print(f"Download: {ok_dl} - {msg_dl or 'Successo'}")
                if ok_dl:
                    dest_path_ftp = f"{test_archive_dir}/{fname_to_test}"
                    print(f"Tentativo spostamento di {fname_to_test} a {dest_path_ftp}...")
                    ok_mv, msg_mv = handler.move_file_on_ftp(fname_to_test, dest_path_ftp)
                    print(f"Spostamento: {ok_mv} - {msg_mv or 'Successo'}")
        else:
            print(msg_cwd_base)

        # Test con una directory documenti fittizia
        test_doc_dir_ftp = "/doc_files_source" # Assicurati che esista sul tuo FTP di test
        handler.ensure_ftp_dir_exists(test_doc_dir_ftp) # Crea se non esiste

        print(f"\nTest listaggio in doc_dir: {test_doc_dir_ftp}")
        ok_cwd_doc, msg_cwd_doc = handler.change_ftp_dir(test_doc_dir_ftp)
        if ok_cwd_doc:
            print(msg_cwd_doc)
            files_doc, err_doc = handler.list_files_in_current_dir()
            if err_doc: print(f"Errore: {err_doc}")
            else: print(f"File in {test_doc_dir_ftp}: {files_doc}")
        else:
            print(msg_cwd_doc)

        handler.disconnect()
        print("Disconnesso.")
    else:
        print(f"Impossibile connettersi a {handler.host}: {handler.get_last_connection_error()}")
