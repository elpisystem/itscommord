import tkinter as tk
import threading
import os
import sys
import pyodbc
import time
import shutil
import datetime
import traceback

import config_loader
import gui_manager
import ftp_handler
import file_processor
import db_importer

def resource_path(relative_path):
    """ Ottiene il percorso assoluto alla risorsa, funziona per dev e per PyInstaller """
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app_config = None
main_gui = None
ftp_conn = None
file_proc = None
db_conn_instance = None

import_thread_worker = None
terminate_import_event = threading.Event()

# === Funzione principale del thread di lavoro ===
def import_worker_task():
    global main_gui, app_config, ftp_conn, file_proc, terminate_import_event, db_conn_instance

    def get_datetime_obj_from_filename(filename_str, expected_prefix):
        # filename_str is the base name, e.g., "divulgaz20250707103411491199_LOST.730"
        # or "20250707100039534941_LOST.730"

        processed_filename = filename_str
        if expected_prefix and processed_filename.startswith(expected_prefix):
            processed_filename = processed_filename[len(expected_prefix):]
            # After removing prefix, if the next char is '_', remove it too if timestamps don't start with it
            # Example: "divulgaz_2025..." -> "_" is part of prefix in some configs, or part of filename structure
            # For "divulgaz2025...", no underscore immediately after prefix.
            # The current file_proc.file_prefix is "divulgaz" (no underscore).
            # So, processed_filename would be "20250707103411491199_LOST.730"

        # Now, processed_filename should start with the date part or be the date part itself
        # Expected: "YYYYMMDDHHMMSSxxxxxx_LOST.730" or "YYYYMMDDHHMMSS_LOST.730"

        timestamp_part_for_extraction = None
        if "_LOST.730" in processed_filename:
            timestamp_part_for_extraction = processed_filename.split('_LOST.730')[0]
        elif "_" in processed_filename: # Fallback if _LOST.730 is not there but another _ is
             timestamp_part_for_extraction = processed_filename.split('_')[0]
        else: # Assume the whole remaining string (or original if no prefix/suffix) is the timestamp part
             timestamp_part_for_extraction = processed_filename

        if timestamp_part_for_extraction and len(timestamp_part_for_extraction) >= 14:
            datetime_str_core = timestamp_part_for_extraction[:14] # YYYYMMDDHHMMSS
            try:
                return datetime.datetime.strptime(datetime_str_core, "%Y%m%d%H%M%S")
            except ValueError:
                if main_gui: main_gui.safe_insert_listbox(f"WARNING: Impossibile convertire '{datetime_str_core}' in datetime da '{filename_str}'. Usando data corrente.", is_error=True)
                return datetime.datetime.now() # Fallback

        if main_gui: main_gui.safe_insert_listbox(f"WARNING: Formato nome file non riconosciuto per estrazione data ('{filename_str}'). Usando data corrente.", is_error=True)
        return datetime.datetime.now() # Fallback

    downloaded_files_info = []
    errors_occurred_task = []
    files_processed_count_ftp_download = 0
    # overall_successful_rows_db and overall_failed_rows_db are now phase-specific
    # overall_successful_rows_db = 0 # old
    # overall_failed_rows_db = 0 # old
    files_for_db_import_final = []
    csv_files_for_lisprelievo_import = [] # New list for CSV file paths
    
    # Counters for final summary
    overall_successful_rows_db_phase4 = 0 
    overall_failed_rows_db_phase4 = 0
    overall_total_doc_testa_imported_phase5 = 0 
    overall_total_doc_righe_imported_phase5 = 0
    overall_total_lisprelievo_imported_phase6 = 0 
    overall_total_lisprelievo_failed_phase6 = 0   


    if main_gui:
        main_gui.show_animation_elements()
        main_gui.safe_set_progress("Avvio importazione...")

    if not file_proc:
        if main_gui: main_gui.show_message("error", "Errore Interno", "File processor non inizializzato.")
        if main_gui: main_gui.hide_animation_elements()
        return

    ok_import_dir, msg_import_dir = file_proc.ensure_local_import_dir_exists()
    if not ok_import_dir:
        if main_gui: main_gui.show_message("error", "Errore Directory", msg_import_dir); main_gui.hide_animation_elements()
        return
    # if main_gui: main_gui.safe_insert_listbox(msg_import_dir) # Dettaglio rimosso

    if app_config.get("ORDINE_DIR"):
        ok_ordine_dir, msg_ordine_dir = file_proc.ensure_ordine_dir_exists()
        if not ok_ordine_dir:
            if main_gui: main_gui.show_message("warning", "Errore Directory Ordine", f"{msg_ordine_dir}.")
            errors_occurred_task.append(f"Creazione/Accesso ORDINE_DIR fallito: {msg_ordine_dir}")
        # elif main_gui: main_gui.safe_insert_listbox(msg_ordine_dir) # Dettaglio rimosso

    if main_gui: main_gui.safe_set_progress("Connessione FTP...")
    if not ftp_conn.connect():
        err_msg = ftp_conn.get_last_connection_error()
        if main_gui: main_gui.safe_set_progress("Errore connessione FTP."); main_gui.show_message("error", "Errore FTP", f"Connessione fallita: {err_msg}"); main_gui.hide_animation_elements()
        return
    # if main_gui: main_gui.safe_insert_listbox(f"Connesso a FTP: {app_config['FTP_HOST']}") # Dettaglio rimosso

    # FASE 1: Download Consolidato
    ftp_base_dir_path = app_config.get("FTP_BASE_DIR", "/")
    ftp_doc_dir_path = app_config.get("FTP_DOC_DIR")

    # --- Inizio Log Semplificato ---
    if main_gui: main_gui.safe_insert_listbox("Ricerca file su server FTP...")

    def _count_files_on_ftp(ftp_dir, file_filter_func):
        if not ftp_dir: return 0
        ok_cwd, _ = ftp_conn.change_ftp_dir(ftp_dir)
        if not ok_cwd: return 0
        remote_files, _ = ftp_conn.list_files_in_current_dir(only_files=True)
        return len([f for f in remote_files if file_filter_func(f)])

    total_files_to_process = 0
    total_files_to_process += _count_files_on_ftp(ftp_base_dir_path, lambda f: f.lower().endswith(".730"))
    total_files_to_process += _count_files_on_ftp(ftp_doc_dir_path, lambda f: f.lower().endswith(".txt"))
    total_files_to_process += _count_files_on_ftp(ftp_doc_dir_path, lambda f: f.lower().endswith(".csv"))
    
    if main_gui:
        if total_files_to_process > 0:
            main_gui.safe_insert_listbox(f"Trovati {total_files_to_process} file totali da elaborare.")
        else:
            main_gui.safe_insert_listbox("Nessun nuovo file trovato sul server FTP.")

    # Funzione interna per scaricare i file in modo generico
    def _download_from_ftp_dir_local(ftp_directory_to_scan, source_type_label, file_filter_func, download_message):
        nonlocal files_processed_count_ftp_download
        if terminate_import_event.is_set(): return []

        ok_cwd, msg_cwd = ftp_conn.change_ftp_dir(ftp_directory_to_scan)
        if not ok_cwd:
            err_msg_cwd = f"Impossibile accedere a directory FTP '{ftp_directory_to_scan}': {msg_cwd}"
            if main_gui: main_gui.safe_insert_listbox(err_msg_cwd, is_error=True)
            errors_occurred_task.append(err_msg_cwd)
            return []

        remote_files, error_list = ftp_conn.list_files_in_current_dir(only_files=True)
        if error_list:
            err_list_msg = f"Errore listando file in {ftp_directory_to_scan}: {error_list}"
            if main_gui: main_gui.safe_insert_listbox(err_list_msg, is_error=True)
            errors_occurred_task.append(err_list_msg)
            return []
        
        files_to_download = [f for f in remote_files if file_filter_func(f)]
        
        if not files_to_download:
            return []

        if main_gui: main_gui.safe_insert_listbox(download_message)
        
        downloaded_batch_info = []
        for fname in files_to_download:
            if terminate_import_event.is_set(): break
            local_temp_path = os.path.join(app_config["LOCAL_IMPORT_DIR"], fname)
            
            dl_success, dl_msg = ftp_conn.download_file(fname, local_temp_path)
            if dl_success:
                downloaded_batch_info.append({
                    "ftp_original_dir": ftp_directory_to_scan,
                    "original_name": fname,
                    "local_temp_path": local_temp_path,
                    "source_type": source_type_label
                })
                files_processed_count_ftp_download += 1
            else:
                dl_err = f"Errore scaricamento {fname} da {ftp_directory_to_scan}: {dl_msg}"
                if main_gui: main_gui.safe_insert_listbox(dl_err, is_error=True)
                errors_occurred_task.append(dl_err)
        
        return downloaded_batch_info

    try:
        if total_files_to_process > 0:
            # Scarica .730
            downloaded_files_info.extend(_download_from_ftp_dir_local(
                ftp_base_dir_path, "BASE_DIR", 
                lambda f: f.lower().endswith(".730"), 
                "Scaricamento delle variazioni (.730)..."
            ))
            if terminate_import_event.is_set(): raise InterruptedError("Download interrotto")

            # Scarica .txt
            if ftp_doc_dir_path:
                downloaded_files_info.extend(_download_from_ftp_dir_local(
                    ftp_doc_dir_path, "DOC_DIR_TXT", 
                    lambda f: f.lower().endswith(".txt"), 
                    "Scaricamento Fatture (.txt)..."
                ))
            if terminate_import_event.is_set(): raise InterruptedError("Download interrotto")
            
            # Scarica .csv
            if ftp_doc_dir_path:
                downloaded_files_info.extend(_download_from_ftp_dir_local(
                    ftp_doc_dir_path, "DOC_DIR_CSV", 
                    lambda f: f.lower().endswith(".csv"), 
                    "Scaricamento Lisprelievo (.csv)..."
                ))
            if terminate_import_event.is_set(): raise InterruptedError("Download interrotto")

            if downloaded_files_info and main_gui:
                main_gui.safe_insert_listbox("Scaricamento completato.")

    except InterruptedError:
        if main_gui: main_gui.safe_insert_listbox("Download interrotto dall'utente.")
    except Exception as e_ftp_dl_phase:
        ftp_dl_err = f"Errore imprevisto durante fase di download FTP: {e_ftp_dl_phase}"
        if main_gui: main_gui.safe_insert_listbox(ftp_dl_err, is_error=True)
        errors_occurred_task.append(ftp_dl_err)
    
    # Ripristina CWD FTP alla base dir
    if ftp_conn.ftp: ftp_conn.change_ftp_dir(ftp_base_dir_path)

    # FASE 2: Processamento Locale
    if not terminate_import_event.is_set() and downloaded_files_info:
        # if main_gui: main_gui.safe_set_progress("Rinomina e copia locale dei file...") # Dettaglio rimosso
        temp_processed_local_files_for_db = []
        for file_info in downloaded_files_info:
            if terminate_import_event.is_set(): break
            original_local_path = file_info["local_temp_path"]
            original_filename = file_info["original_name"]
            source_type = file_info["source_type"]

            new_final_local_filename = ""
            if source_type == "BASE_DIR":
                new_final_local_filename = f"{file_proc.file_prefix}{original_filename}"
            elif source_type == "DOC_DIR_TXT":
                base, ext = os.path.splitext(original_filename)
                timestamp = time.strftime("%Y%m%d%H%M%S")
                new_final_local_filename = f"{timestamp}_{base}{ext}"
            elif source_type == "DOC_DIR_CSV":
                new_final_local_filename = original_filename # No rename for CSVs
            else:
                new_final_local_filename = original_filename

            if not new_final_local_filename: continue

            final_local_path_in_import_dir = os.path.join(app_config["LOCAL_IMPORT_DIR"], new_final_local_filename)
            try:
                if os.path.exists(original_local_path):
                    if original_local_path != final_local_path_in_import_dir:
                        shutil.move(original_local_path, final_local_path_in_import_dir)
                        # if main_gui: main_gui.safe_insert_listbox(f"Spostato/Rinominato in locale: {original_filename} -> {new_final_local_filename}") # Dettaglio rimosso
                    # else:
                         # if main_gui: main_gui.safe_insert_listbox(f"File {new_final_local_filename} già con nome finale in directory temporanea.") # Dettaglio rimosso
                    
                    file_info["final_local_path"] = final_local_path_in_import_dir
                    file_info["final_local_name"] = new_final_local_filename
                    
                    path_for_db_processing = None

                    if app_config.get("ORDINE_DIR"):
                        dest_path_ordine_dir = os.path.join(app_config["ORDINE_DIR"], new_final_local_filename)
                        try:
                            shutil.copy2(final_local_path_in_import_dir, dest_path_ordine_dir)
                            # if main_gui: main_gui.safe_insert_listbox(f"Copiato: {new_final_local_filename} → {app_config['ORDINE_DIR']}") # Dettaglio rimosso
                            path_for_db_processing = dest_path_ordine_dir
                        except Exception as e_copy_ordine:
                            copy_err = f"Errore copia {new_final_local_filename} → {app_config['ORDINE_DIR']}: {e_copy_ordine}"
                            if main_gui: main_gui.safe_insert_listbox(copy_err, is_error=True)
                            errors_occurred_task.append(copy_err)
                            path_for_db_processing = final_local_path_in_import_dir 
                    else:
                        path_for_db_processing = final_local_path_in_import_dir

                    if source_type == "BASE_DIR":
                        temp_processed_local_files_for_db.append(path_for_db_processing)
                    elif source_type == "DOC_DIR_CSV":
                        csv_files_for_lisprelievo_import.append(path_for_db_processing)
                else:
                    missing_err = f"File sorgente {original_filename} non trovato per rinomina."
                    if main_gui: main_gui.safe_insert_listbox(missing_err, is_error=True)
                    errors_occurred_task.append(missing_err)
            except Exception as e_rename_copy:
                rc_err = f"Errore rinomina/copia locale per {original_filename}: {e_rename_copy}"
                if main_gui: main_gui.safe_insert_listbox(rc_err, is_error=True)
                errors_occurred_task.append(rc_err)
        
        if temp_processed_local_files_for_db:
            # if main_gui: main_gui.safe_insert_listbox("Ordinamento file .730 per data/ora...") # Dettaglio rimosso
            try:
                def get_timestamp_from_filename(filepath):
                    filename = os.path.basename(filepath)
                    parts = filename.split('_')
                    if len(parts) > 1 and parts[0] == file_proc.file_prefix and len(parts[1]) >= 14:
                        return parts[1][:14]
                    return "00000000000000"

                temp_processed_local_files_for_db.sort(key=get_timestamp_from_filename)
                
                # if main_gui:
                #     main_gui.safe_insert_listbox("File .730 ordinati per importazione:")
                #     for sorted_fpath in temp_processed_local_files_for_db:
                #         main_gui.safe_insert_listbox(f"  - {os.path.basename(sorted_fpath)}") # Dettaglio rimosso
            except Exception as e_sort:
                sort_err = f"Errore durante l'ordinamento dei file .730: {e_sort}"
                if main_gui: main_gui.safe_insert_listbox(sort_err, is_error=True)
                errors_occurred_task.append(sort_err)
        
        files_for_db_import_final = list(temp_processed_local_files_for_db)

        if terminate_import_event.is_set():
            if ftp_conn.ftp: ftp_conn.disconnect()
            return

    # FASE 3: Spostamento Archivio FTP
    if ftp_conn.ftp and not terminate_import_event.is_set() and downloaded_files_info:
        # if main_gui: main_gui.safe_set_progress("Archiviazione file su FTP...") # Dettaglio rimosso

        ftp_target_dir_base_archive = app_config.get("FTP_TARGET_DIR", "/importati")
        ok_base_archive, msg_base_archive = ftp_conn.ensure_ftp_dir_exists(ftp_target_dir_base_archive)
        # if main_gui: main_gui.safe_insert_listbox(msg_base_archive, is_error=not ok_base_archive) # Dettaglio rimosso
        if not ok_base_archive: errors_occurred_task.append(f"Creazione dir archivio {ftp_target_dir_base_archive} fallita: {msg_base_archive}")

        ftp_doc_target_archive_dir_path = "/DOC_importati"
        ok_doc_archive = False

        if app_config.get("FTP_DOC_DIR"):
            ok_doc_archive, msg_doc_archive = ftp_conn.ensure_ftp_dir_exists(ftp_doc_target_archive_dir_path)
            # if main_gui: main_gui.safe_insert_listbox(msg_doc_archive, is_error=not ok_doc_archive) # Dettaglio rimosso
            if not ok_doc_archive:
                errors_occurred_task.append(f"Creazione/accesso dir archivio DOC '{ftp_doc_target_archive_dir_path}' fallita: {msg_doc_archive}")

        for file_info in downloaded_files_info:
            if terminate_import_event.is_set(): break
            original_ftp_fname = file_info["original_name"]
            source_ftp_dir_of_file = file_info["ftp_original_dir"]

            perform_ftp_move = False
            dest_ftp_archive_dir_for_file = None

            if file_info["source_type"] == "BASE_DIR":
                if ok_base_archive:
                    dest_ftp_archive_dir_for_file = ftp_target_dir_base_archive
                    perform_ftp_move = True
                else:
                    if main_gui: main_gui.safe_insert_listbox(f"Archivio FTP base non pronto, spostamento di {original_ftp_fname} saltato.", is_error=True)
            
            elif file_info["source_type"].startswith("DOC_DIR"):
                if ok_doc_archive:
                    dest_ftp_archive_dir_for_file = ftp_doc_target_archive_dir_path
                    perform_ftp_move = True
                else:
                    if main_gui: main_gui.safe_insert_listbox(f"Archivio FTP DOC non pronto, spostamento di {original_ftp_fname} saltato.", is_error=True)

            if perform_ftp_move and dest_ftp_archive_dir_for_file:
                if ftp_conn.get_current_ftp_dir() != source_ftp_dir_of_file:
                    ok_cwd_source, msg_cwd_source = ftp_conn.change_ftp_dir(source_ftp_dir_of_file)
                    if not ok_cwd_source:
                        err_msg_cwd = f"Impossibile CWD a '{source_ftp_dir_of_file}' per spostare '{original_ftp_fname}': {msg_cwd_source}"
                        if main_gui: main_gui.safe_insert_listbox(err_msg_cwd, is_error=True)
                        errors_occurred_task.append(err_msg_cwd)
                        continue

                full_target_ftp_file_path_for_move = f"{dest_ftp_archive_dir_for_file.rstrip('/')}/{original_ftp_fname}"
                mv_success, mv_msg = ftp_conn.move_file_on_ftp(original_ftp_fname, full_target_ftp_file_path_for_move)
                if not mv_success:
                    err_mv_ftp = f"Errore spostamento FTP {original_ftp_fname}: {mv_msg}"
                    if main_gui: main_gui.safe_insert_listbox(err_mv_ftp, is_error=True)
                    errors_occurred_task.append(err_mv_ftp)

        final_ftp_base_dir_after_ops = app_config.get("FTP_BASE_DIR", "/")
        if ftp_conn.ftp and ftp_conn.get_current_ftp_dir() != final_ftp_base_dir_after_ops:
             ftp_conn.change_ftp_dir(final_ftp_base_dir_after_ops)

    if ftp_conn.ftp:
        ftp_conn.disconnect()
        # if main_gui: main_gui.safe_insert_listbox("Disconnesso da FTP.") # Dettaglio rimosso


    # FASE 4: Importazione Database
    if db_conn_instance and (files_for_db_import_final or csv_files_for_lisprelievo_import or any(fi.get("source_type") == "DOC_DIR_TXT" for fi in downloaded_files_info)) and not terminate_import_event.is_set():
        if main_gui:
            main_gui.safe_set_progress("Aggiornamento Gestione Ordini...")
            main_gui.safe_insert_listbox("Aggiornamento Gestione Ordini in corso...")

        db_connection_ok, db_conn_msg = db_conn_instance.connect()
        if not db_connection_ok:
            db_conn_err_msg = f"Errore connessione DB: {db_conn_msg}"
            if main_gui: main_gui.safe_insert_listbox(db_conn_err_msg, is_error=True); main_gui.show_message("error", "Errore Database", f"Impossibile connettersi al database: {db_conn_msg}")
            errors_occurred_task.append(db_conn_err_msg)
        else:
            # if main_gui: main_gui.safe_insert_listbox(f"Connesso al Database: {app_config['DB_NAME']}") # Dettaglio rimosso
            
            # --- Importazione .730 ---
            # FIX: Initialize aggregation lists to prevent UnboundLocalError
            aggregated_prodotti_for_direct = []
            aggregated_anarti_needing_lookup = []
            if files_for_db_import_final:
                overall_successful_rows_db_phase4 = 0
                overall_failed_rows_db_phase4 = 0
                insert_order = ["ANAFOR", "ANARTI", "ARTEAN", "ARTLEG", "VARLIS"]
                all_files_parsed_data = {rt: {"schema": None, "target_table": None, "col_names": None, "rows_values": []} for rt in insert_order}

                for full_filepath_to_import in files_for_db_import_final:
                    if terminate_import_event.is_set(): break
                    filename_to_import = os.path.basename(full_filepath_to_import)
                    current_file_parsing_errors_for_log = []
                    current_file_status = "SUCCESS"

                    source_file_datetime = get_datetime_obj_from_filename(filename_to_import, file_proc.file_prefix)
                    
                    parsed_data_this_file, pfd_this_file, anl_this_file, parsing_errors_this_file = \
                        file_proc.process_file_for_db_import(full_filepath_to_import, app_config.get("FILE_LAYOUTS", {}))

                    if pfd_this_file:
                        for pf_dict in pfd_this_file: pf_dict['__source_file_datetime'] = source_file_datetime
                        aggregated_prodotti_for_direct.extend(pfd_this_file)
                    if anl_this_file:
                        for anarti_dict in anl_this_file: anarti_dict['__source_file_datetime'] = source_file_datetime
                        aggregated_anarti_needing_lookup.extend(anl_this_file)

                    if parsing_errors_this_file:
                        current_file_status = "PARTIAL_SUCCESS_PARSING_ERRORS" if parsed_data_this_file else "FAILED_PARSING"
                        for err_msg in parsing_errors_this_file:
                            gui_err_msg = f"File {filename_to_import} (Parsing): {err_msg}"
                            if main_gui: main_gui.safe_insert_listbox(gui_err_msg, is_error=True)
                            errors_occurred_task.append(gui_err_msg)

                    if not parsed_data_this_file and not parsing_errors_this_file:
                        current_file_status = "SKIPPED_EMPTY_OR_NO_DATA"
                    
                    if parsed_data_this_file:
                        for record_type, data_dict in parsed_data_this_file.items():
                            if record_type in all_files_parsed_data:
                                if not all_files_parsed_data[record_type]["col_names"]:
                                    all_files_parsed_data[record_type].update({
                                        "col_names": list(data_dict["col_names"]), "schema": data_dict["schema"], "target_table": data_dict["target_table"]
                                    })
                                    if record_type == "VARLIS" and "DATA_INS" not in all_files_parsed_data[record_type]["col_names"]:
                                        all_files_parsed_data[record_type]["col_names"].append("DATA_INS")
                                
                                if record_type == "VARLIS":
                                    augmented_rows = [row + (source_file_datetime.date() if source_file_datetime else None,) for row in data_dict["rows_values"]]
                                    all_files_parsed_data[record_type]["rows_values"].extend(augmented_rows)
                                else:
                                    all_files_parsed_data[record_type]["rows_values"].extend(data_dict["rows_values"])
                
                # Importazione aggregata
                for record_type_to_insert in insert_order:
                    if terminate_import_event.is_set(): break
                    agg_data = all_files_parsed_data.get(record_type_to_insert)
                    if agg_data and agg_data["rows_values"]:
                        s_rows, errors_db = 0, []
                        if record_type_to_insert == "VARLIS":
                            s_rows, errors_db = db_conn_instance.insert_varlis_batch(agg_data["rows_values"], agg_data["col_names"], agg_data["schema"])
                        else:
                            pk_cols = [c["name"] for c in app_config.get("FILE_LAYOUTS", {}).get(record_type_to_insert, {}).get("columns", []) if c.get("is_pk")]
                            s_rows, errors_db = db_conn_instance.upsert_data_batch(agg_data["target_table"], agg_data["rows_values"], agg_data["col_names"], pk_cols, agg_data["schema"])

                        overall_successful_rows_db_phase4 += s_rows
                        num_failed = len(agg_data["rows_values"]) - s_rows
                        overall_failed_rows_db_phase4 += num_failed
                        if errors_db:
                            for db_error_str in errors_db:
                                gui_db_err_msg = f"Tabella {agg_data['target_table']}: {db_error_str}"
                                if main_gui: main_gui.safe_insert_listbox(gui_db_err_msg, is_error=True)
                                errors_occurred_task.append(gui_db_err_msg)

                # Archiviazione .730
                for fpath in files_for_db_import_final:
                    if terminate_import_event.is_set(): break
                    fname = os.path.basename(fpath)
                    if app_config.get("ORDINE_DIR"):
                        save_subdir = os.path.join(app_config["ORDINE_DIR"], "Save")
                        if not os.path.exists(save_subdir): os.makedirs(save_subdir, exist_ok=True)
                        dest_path = os.path.join(save_subdir, fname)
                        try:
                            if os.path.exists(fpath): shutil.move(fpath, dest_path)
                        except Exception as e_archive:
                            archive_err = f"Errore archiviazione {fname}: {e_archive}"
                            if main_gui: main_gui.safe_insert_listbox(archive_err, is_error=True)
                            errors_occurred_task.append(archive_err)

            # --- Popolamento PRODOTTI_FOR ---
            if db_conn_instance.conn and not terminate_import_event.is_set() and (aggregated_prodotti_for_direct or aggregated_anarti_needing_lookup):
                prodotti_for_final_dictionaries = []
                prodotti_for_final_dictionaries.extend(aggregated_prodotti_for_direct)

                if aggregated_anarti_needing_lookup:
                    unique_ult_cod_forni_to_lookup = list(set(
                        str(d.get("ULT_COD_FORNI", "")).strip() for d in aggregated_anarti_needing_lookup if d.get("ULT_COD_FORNI")
                    ))
                    if unique_ult_cod_forni_to_lookup:
                        anafor_from_db_map = db_conn_instance.get_anafor_by_cod_forni_list(
                            unique_ult_cod_forni_to_lookup, schema=app_config.get("DB_DEFAULT_SCHEMA", "dbo")
                        )
                        for anarti_nl_dict in aggregated_anarti_needing_lookup:
                            ult_cod_forni_raw = str(anarti_nl_dict.get("ULT_COD_FORNI", "")).strip()
                            ult_cod_forni_key = ult_cod_forni_raw
                            if ult_cod_forni_raw.isdigit():
                                try: ult_cod_forni_key = str(int(ult_cod_forni_raw))
                                except ValueError: pass
                            
                            anafor_db_rec = anafor_from_db_map.get(ult_cod_forni_key)
                            if anafor_db_rec:
                                prod_for_dict = {**anarti_nl_dict, **anafor_db_rec}
                                prodotti_for_final_dictionaries.append(prod_for_dict)
                
                if prodotti_for_final_dictionaries:
                    prodotti_for_rows_to_upsert = []
                    prodotti_for_cols_order = [
                        "COD_ART", "COD_EAN_ULT_INS", "DES", "UN_MIS", "TIPO_UN_MIS", "COD_FORNI", "P_IVA_FORNI", "RAGSOC", 
                        "INDIRIZZO", "LOCALITA", "PROV", "CAP", "TEL", "FAX", "EMAIL", "COD_ART_FORNI_1", "COD_ART_FORNI_2", 
                        "COD_ART_FORNI_3", "AREA", "SETTORE", "COMPARTO", "FAM", "SUB_FAM", "AL_IVA", "STATO_ART", "IMB", 
                        "PZ_X_CART", "CART_X_PALLET", "GEST_POS", "LEGAME", "DATA_AGG", "FASC_APP", "REP_CASSA", "PLU", "ASSORT_SN"
                    ]
                    prodotti_for_pk_cols = ["COD_ART", "COD_FORNI"]

                    for pf_dict in prodotti_for_final_dictionaries:
                        file_dt = pf_dict.pop('__source_file_datetime', None)
                        pf_dict["DATA_AGG"] = file_dt if file_dt else datetime.datetime.now()
                        try:
                            for key in ["COD_ART", "COD_FORNI", "CART_X_PALLET"]:
                                if pf_dict.get(key) is not None:
                                    if isinstance(pf_dict[key], str) and pf_dict[key].isdigit():
                                        pf_dict[key] = int(pf_dict[key])
                                    elif not isinstance(pf_dict[key], int):
                                        pf_dict[key] = int(float(pf_dict[key]))
                            row_tuple = tuple(pf_dict.get(col) for col in prodotti_for_cols_order)
                            prodotti_for_rows_to_upsert.append(row_tuple)
                        except (ValueError, TypeError) as e_conv:
                            conv_err_msg = f"PRODOTTI_FOR: Errore conversione per ART '{pf_dict.get('COD_ART')}' / FOR '{pf_dict.get('COD_FORNI')}': {e_conv}. Riga saltata."
                            if main_gui: main_gui.safe_insert_listbox(conv_err_msg, is_error=True)
                            errors_occurred_task.append(conv_err_msg)
                    
                    if prodotti_for_rows_to_upsert:
                        pf_s_rows, pf_errors_db = db_conn_instance.upsert_data_batch(
                            "PRODOTTI_FOR", prodotti_for_rows_to_upsert, prodotti_for_cols_order, 
                            prodotti_for_pk_cols, schema=app_config.get("DB_DEFAULT_SCHEMA", "dbo")
                        )
                        if pf_errors_db:
                            for err in pf_errors_db:
                                errors_occurred_task.append(f"PRODOTTI_FOR DB: {err}")
                                if main_gui: main_gui.safe_insert_listbox(f"PRODOTTI_FOR DB: {err}", is_error=True)

            # --- Importazione Fatture TXT ---
            if db_conn_instance.conn and not terminate_import_event.is_set() and file_proc:
                invoice_files_to_process = []
                for file_info_inv in downloaded_files_info:
                    if file_info_inv.get("source_type") == "DOC_DIR_TXT":
                        path_to_check = os.path.join(app_config.get("ORDINE_DIR", ""), file_info_inv.get("final_local_name", ""))
                        if os.path.exists(path_to_check):
                            invoice_files_to_process.append(path_to_check)
                        elif os.path.exists(file_info_inv.get("final_local_path", "")):
                            invoice_files_to_process.append(file_info_inv.get("final_local_path"))
                        else:
                            missing_inv_msg = f"File fattura .txt '{file_info_inv.get('final_local_name', 'SCONOSCIUTO')}' non trovato per l'importazione."
                            if main_gui: main_gui.safe_insert_listbox(missing_inv_msg, is_error=True)
                            errors_occurred_task.append(missing_inv_msg)
                
                if invoice_files_to_process:
                    for txt_filepath in invoice_files_to_process:
                        if terminate_import_event.is_set(): break
                        filename_inv = os.path.basename(txt_filepath)
                        parsed_invoice_data = file_proc.process_invoice_txt_file(txt_filepath)
                        
                        if parsed_invoice_data:
                            if parsed_invoice_data.get("doc_testa"):
                                count_h, errors_h, newly_inserted_num_docs = db_conn_instance.upsert_doc_testa_batch(parsed_invoice_data["doc_testa"])
                                overall_total_doc_testa_imported_phase5 += count_h
                                if errors_h:
                                    for err in errors_h:
                                        if main_gui: main_gui.safe_insert_listbox(f"Errore DOC_TESTA ({filename_inv}): {err}", is_error=True)
                                        errors_occurred_task.append(f"File {filename_inv}, DOC_TESTA: {err}")
                                
                                if parsed_invoice_data.get("doc_righe") and newly_inserted_num_docs:
                                    righe_to_insert = [r for r in parsed_invoice_data["doc_righe"] if r.get("NUM_DOC") in newly_inserted_num_docs]
                                    if righe_to_insert:
                                        count_r, errors_r = db_conn_instance.insert_doc_righe_batch(righe_to_insert)
                                        overall_total_doc_righe_imported_phase5 += count_r
                                        if errors_r:
                                            for err in errors_r:
                                                if main_gui: main_gui.safe_insert_listbox(f"Errore DOC_RIGHE ({filename_inv}): {err}", is_error=True)
                                                errors_occurred_task.append(f"File {filename_inv}, DOC_RIGHE: {err}")
                        else:
                            no_data_err_msg = f"Nessun dato valido estratto da {filename_inv}."
                            if main_gui: main_gui.safe_insert_listbox(no_data_err_msg, is_error=True)
                            errors_occurred_task.append(no_data_err_msg)

                        # Archiviazione .txt
                        if app_config.get("ORDINE_DIR"):
                            save_subdir_txt = os.path.join(app_config["ORDINE_DIR"], "Save")
                            if not os.path.exists(save_subdir_txt): os.makedirs(save_subdir_txt, exist_ok=True)
                            dest_path_txt = os.path.join(save_subdir_txt, filename_inv)
                            try:
                                if os.path.abspath(txt_filepath) != os.path.abspath(dest_path_txt):
                                    shutil.move(txt_filepath, dest_path_txt)
                            except Exception as e_archive_txt:
                                archive_err_txt = f"Errore archiviazione {filename_inv}: {e_archive_txt}"
                                if main_gui: main_gui.safe_insert_listbox(archive_err_txt, is_error=True)
                                errors_occurred_task.append(archive_err_txt)

            # --- Importazione LISPRELIEVO da CSV ---
            if db_conn_instance.conn and not terminate_import_event.is_set() and file_proc and csv_files_for_lisprelievo_import:
                for csv_filepath in csv_files_for_lisprelievo_import:
                    if terminate_import_event.is_set(): break
                    filename_csv = os.path.basename(csv_filepath)
                    n_lista = None
                    try:
                        parts = os.path.splitext(filename_csv)[0].split('_')
                        if len(parts) == 3 and parts[0].upper() == "LISTA" and parts[1].upper() == "PRELIEVO" and parts[2].isdigit():
                            n_lista = parts[2]
                        else:
                            raise ValueError("Formato nome file non valido.")
                    except Exception as e:
                        name_err = f"Nome file CSV '{filename_csv}' non valido: {e}"
                        if main_gui: main_gui.safe_insert_listbox(name_err, is_error=True)
                        errors_occurred_task.append(name_err)
                        continue

                    exists, check_err = db_conn_instance.check_n_lista_exists(n_lista)
                    if check_err:
                        check_fail_msg = f"Errore verifica N_LISTA '{n_lista}' per {filename_csv}: {check_err}."
                        if main_gui: main_gui.safe_insert_listbox(check_fail_msg, is_error=True)
                        errors_occurred_task.append(check_fail_msg)
                        continue
                    if exists:
                        # Non è un errore, ma un'informazione. La saltiamo in silenzio per l'utente finale.
                        continue

                    parsed_csv_data = file_proc.process_lisprelievo_csv_file(csv_filepath)
                    if parsed_csv_data:
                        count_csv, errors_csv_db = db_conn_instance.insert_lisprelievo_batch(parsed_csv_data)
                        overall_total_lisprelievo_imported_phase6 += count_csv
                        overall_total_lisprelievo_failed_phase6 += (len(parsed_csv_data) - count_csv)
                        if errors_csv_db:
                            for err in errors_csv_db:
                                if main_gui: main_gui.safe_insert_listbox(f"Errore LISPRELIEVO ({filename_csv}): {err}", is_error=True)
                                errors_occurred_task.append(f"File {filename_csv}, LISPRELIEVO: {err}")
                    
                    # Archiviazione .csv
                    if app_config.get("ORDINE_DIR"):
                        save_dir_csv = os.path.join(app_config["ORDINE_DIR"], "SAVE")
                        if not os.path.exists(save_dir_csv): os.makedirs(save_dir_csv, exist_ok=True)
                        dest_path_csv = os.path.join(save_dir_csv, filename_csv)
                        try:
                            if os.path.exists(csv_filepath): shutil.move(csv_filepath, dest_path_csv)
                        except Exception as e_archive_csv:
                            archive_err_csv = f"Errore archiviazione {filename_csv}: {e_archive_csv}"
                            if main_gui: main_gui.safe_insert_listbox(archive_err_csv, is_error=True)
                            errors_occurred_task.append(archive_err_csv)
            
            if main_gui:
                main_gui.safe_insert_listbox("Aggiornamento completato.")

    # Riepilogo finale
    if main_gui:
        main_gui.hide_animation_elements()
        final_progress_message = "Operazione completata"
        if terminate_import_event.is_set():
            final_progress_message = "Operazione interrotta."

        summary_lines = [f"{files_processed_count_ftp_download} file totali scaricati da FTP."]
        if db_conn_instance and app_config.get("FILE_LAYOUTS") and (overall_successful_rows_db_phase4 > 0 or overall_failed_rows_db_phase4 > 0 or files_for_db_import_final):
            summary_lines.append(f"Importazione DB (.730): {overall_successful_rows_db_phase4} righe processate, {overall_failed_rows_db_phase4} righe fallite.")
        
        # Summary for TXT Invoices (Phase 5) added already by previous commit, ensure it's here
        if overall_total_doc_testa_imported_phase5 > 0 or overall_total_doc_righe_imported_phase5 > 0:
             summary_lines.append(f"Importazione Fatture TXT: {overall_total_doc_testa_imported_phase5} testate, {overall_total_doc_righe_imported_phase5} righe.")
        
        # Summary for CSV LISPRELIEVO (Phase 6) added already by previous commit, ensure it's here
        if overall_total_lisprelievo_imported_phase6 > 0 or overall_total_lisprelievo_failed_phase6 > 0:
            summary_lines.append(f"Importazione LISPRELIEVO CSV: {overall_total_lisprelievo_imported_phase6} righe importate, {overall_total_lisprelievo_failed_phase6} righe fallite.")

        if errors_occurred_task:
            final_progress_message = f"Completato con {len(errors_occurred_task)} errori."
            summary_lines.append(f"Si sono verificati {len(errors_occurred_task)} errori totali.")
            summary_message_type = "warning"; summary_title = "Completato con Errori"
        elif files_processed_count_ftp_download == 0 and not downloaded_files_info: # Corrected this condition
             summary_message_type = "info"; summary_title = "Completato" 
        else: 
            summary_message_type = "info"; summary_title = "Completato"


        main_gui.safe_set_progress(final_progress_message)
        if errors_occurred_task:
            error_details_summary = "\n".join(errors_occurred_task[:7])
            if len(errors_occurred_task) > 7: error_details_summary += f"\n...e altri {len(errors_occurred_task) - 7} errori."
            summary_lines.append(f"\nPrimi errori:\n{error_details_summary}")
        main_gui.show_message(summary_message_type, summary_title, "\n".join(summary_lines))

    terminate_import_event.clear()

def start_import_process():
    global import_thread_worker, terminate_import_event, main_gui
    if import_thread_worker and import_thread_worker.is_alive():
        if main_gui: main_gui.show_message("warning", "Attenzione", "Importazione già in corso.")
        return
    terminate_import_event.clear()
    if main_gui:
        main_gui.terminate_import = False
        main_gui.file_listbox.delete(0, tk.END)
        main_gui.progress_label.config(text="")
    import_thread_worker = threading.Thread(target=import_worker_task, daemon=True)
    import_thread_worker.start()

def handle_app_closing():
    global import_thread_worker, terminate_import_event, main_gui, db_conn_instance
    close_app = True
    if import_thread_worker and import_thread_worker.is_alive():
        if main_gui:
            if main_gui.ask_yes_no("Conferma Uscita", "Importazione in corso. Interrompere e uscire?"):
                terminate_import_event.set()
                if main_gui: main_gui.terminate_import = True
            else:
                close_app = False
    if close_app:
        if db_conn_instance and db_conn_instance.conn:
            print("Chiusura connessione DB durante l'uscita dall'applicazione...")
            db_conn_instance.disconnect()
        if main_gui:
            main_gui.destroy_window()

if __name__ == "__main__":
    db_conn_instance = None
    try:
        config_path = resource_path("ftp_itscommconfig.xml")
        app_config = config_loader.load_app_config(config_path)
    except SystemExit:
        sys.exit(1)
    except Exception as e_conf:
        print(f"Errore FATALE durante il caricamento della configurazione: {e_conf}")
        try:
            root_err = tk.Tk()
            root_err.withdraw()
            messagebox.showerror("Errore Configurazione Fatale", f"Impossibile avviare l'applicazione:\n{e_conf}")
            root_err.destroy()
        except:
            pass
        sys.exit(1)

    ftp_conn = ftp_handler.FTPHandler(
        app_config.get("FTP_HOST"),
        app_config.get("FTP_USER"),
        app_config.get("FTP_PASS"),
        app_config.get("FTP_BASE_DIR", "/"),
        app_config.get("FTP_TARGET_DIR", "/importati")
    )
    file_proc = file_processor.FileProcessor(
        app_config.get("LOCAL_IMPORT_DIR"),
        app_config.get("ORDINE_DIR"),
    )

    if app_config.get("DB_DRIVER") and \
       app_config.get("DB_SERVER") and \
       app_config.get("DB_NAME") and \
       app_config.get("DB_USER") is not None and \
       app_config.get("DB_PASS") is not None and \
       app_config.get("FILE_LAYOUTS"):
        db_conn_instance = db_importer.DBImporter(
            driver=app_config["DB_DRIVER"],
            server=app_config["DB_SERVER"],
            database_name=app_config["DB_NAME"],
            username=app_config["DB_USER"],
            password=app_config["DB_PASS"]
        )
    else:
        print("Avviso: Configurazione database/layout file incompleta o FILE_LAYOUTS non definiti. L'importazione DB sarà saltata.")

    root = tk.Tk()

    # Fetch PV info before GUI initialization
    pv_display_info = "PV: N/A" # Default
    if app_config.get("DB_DRIVER") and app_config.get("DB_SERVER") and \
       app_config.get("DB_NAME") and app_config.get("DB_USER") is not None and \
       app_config.get("DB_PASS") is not None:
        try:
            # Adjusted DRIVER format: if DB_DRIVER is "SQL Server", this becomes "DRIVER={SQL Server};"
            # If DB_DRIVER from config is "{SQL Server}", this would become "DRIVER={{SQL Server}};" which might be wrong.
            # Assuming DB_DRIVER in config does NOT have braces.
            driver_name_pv = app_config['DB_DRIVER']
            if not driver_name_pv.startswith('{') and not driver_name_pv.endswith('}'):
                driver_name_pv = f"{{{driver_name_pv}}}" # Add braces if not present

            conn_str_pv = (
                f"DRIVER={driver_name_pv};"
                f"SERVER={app_config['DB_SERVER']};"
                f"DATABASE={app_config['DB_NAME']};"
                f"UID={app_config['DB_USER']};"
                f"PWD={app_config['DB_PASS']};"
                # Consider adding a short login timeout if startup speed is critical
                # f"LoginTimeout=5;" 
            )
            # Using a short-lived connection for this startup query
            pv_conn = None
            try:
                pv_conn = pyodbc.connect(conn_str_pv, autocommit=True)
                pv_cursor = pv_conn.cursor()
                # Assuming SQL Server syntax with TOP 1. Adjust if DB is different.
                # Also assuming 'puntiv' table is in the default schema (e.g. dbo)
                query_puntiv = "SELECT TOP 1 COD_PV, DES_PV FROM puntiv"
                pv_cursor.execute(query_puntiv)
                row = pv_cursor.fetchone()
                if row and len(row) == 2:
                    cod_pv = row[0] if row[0] is not None else ""
                    des_pv = row[1] if row[1] is not None else ""
                    pv_display_info = f"PV: {cod_pv} {des_pv}".strip()
                    if pv_display_info == "PV:": # Handle case where both might be empty strings
                        pv_display_info = "PV: Data not found"
                else:
                    pv_display_info = "PV: Puntiv data not found"
                pv_cursor.close()
            except pyodbc.Error as e_pv_sql:
                print(f"MAIN: Errore SQL durante recupero info PV da 'puntiv': {e_pv_sql}")
                pv_display_info = "PV: Errore DB"
            except Exception as e_pv_general:
                print(f"MAIN: Errore generale durante recupero info PV: {e_pv_general}")
            finally:
                if pv_conn:
                    pv_conn.close()
        except Exception as e_pv_conn_setup:
            # This might catch errors in config values for the connection string itself
            print(f"MAIN: Errore configurazione connessione DB per info PV: {e_pv_conn_setup}")
            pv_display_info = "PV: Errore Config DB"
    else:
        print("MAIN: Configurazione DB per info PV incompleta. Info PV non caricata.")
        # pv_display_info remains "PV: N/A" or could be set to "PV: Config DB mancante"

    # Pass the fetched info (or default) to the GUI
    # The app_config will also be passed, but pv_display_info is now specific
    main_gui = gui_manager.AppGUI(root, app_config, pv_display_info,
                                  start_import_callback=start_import_process,
                                  on_close_callback=handle_app_closing)

    root.mainloop()
    print("Applicazione terminata.")
