import os
import time
import sqlite3
import subprocess
import json
import cv2
import numpy as np
import logging
import multiprocessing


def logger(id, file_name):
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'{id}_{file_name}.log')
    logger = logging.getLogger(file_name)
    logger.setLevel(logging.DEBUG)
    if logger.hasHandlers():
        logger.handlers.clear()
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

def create_db_connection():
    return sqlite3.connect('media_info.db')

def audio_encode(id, file_path, selected_audio, path_output, start_tc, end_tc, infade, outfade, outfade_start):
    conn = create_db_connection()
    cursor = conn.cursor()
    track_number = selected_audio
    cursor.execute('''
        SELECT channels, stream_index
        FROM audio_tracks
        WHERE media_info_id = ? AND track_number = ?
    ''', (id, track_number))
    channels, stream_index = cursor.fetchone()
    
    conn.close()
    audio_file = os.path.join(path_output, str(id) + '_stereo.m4a')

    try:
        if '1' in str(channels) or '2' in str(channels):
            cmd = [
                'ffmpeg',
                '-y',
                '-i', file_path,
                '-ss', start_tc,
                '-to', end_tc,
                '-vn',
                '-map', f'0:{stream_index}',
                '-af', f'afade=in:0:d={infade},afade=out:st={outfade_start}:d={outfade}',
                '-c:a', 'aac',
                '-ac', '2',
                '-b:a', '320k',
                '-ar', '48000',
                '-map_metadata', '-1',
                audio_file
            ]
        else:
            cmd = [
                'ffmpeg',
                '-y',
                '-i', file_path,
                '-ss', start_tc,
                '-to', end_tc,
                '-vn',
                '-map', f'0:{stream_index}',
                '-c:a', 'aac',
                '-af', f'pan=stereo|FL < 1.0*FL + 0.707*FC + 0.707*BL|FR < 1.0*FR + 0.707*FC + 0.707*BR,afade=in:0:d={infade},afade=out:st={outfade_start}:d={outfade}',
                '-b:a', '320k',
                '-ar', '48000',
                '-map_metadata', '-1',
                audio_file
            ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return audio_file
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка при обработке аудио: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка при обработке аудио: {e}")

def extract_normalization_data(id, file_name, audio_file):
    try:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "info",
            '-y',
            "-i",
            audio_file,
            "-af",
            "loudnorm=I=-23:LRA=11:TP=-2:print_format=json",
            "-f",
            "null",
            "-",
        ]
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8')
        output_lines = output.strip().split("\n")
        normalization_data = parse_loudnorm_output(id, file_name, output_lines)
        return normalization_data
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка при получении данных нормализации: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка при получении данных нормализации: {e}")

def parse_loudnorm_output(id, file_name, output_lines):
    log = logger(id, file_name)
    loudnorm_start = False
    loudnorm_end = False
    for index, line in enumerate(output_lines):
        if line.startswith("[Parsed_loudnorm"):
            loudnorm_start = index + 1
            continue
        if loudnorm_start and line.startswith("}"):
            loudnorm_end = index + 1
            break
    if not (loudnorm_start and loudnorm_end):
        raise Exception("Could not parse loudnorm stats; no loudnorm-related output found")
    try:
        loudnorm_stats = json.loads("\n".join(output_lines[loudnorm_start:loudnorm_end]))
        for key in [
            "input_i",
            "input_tp",
            "input_lra",
            "input_thresh",
            "output_i",
            "output_tp",
            "output_lra",
            "output_thresh",
            "target_offset",
        ]:
            if float(loudnorm_stats[key]) == -float("inf"):
                loudnorm_stats[key] = -99
            elif float(loudnorm_stats[key]) == float("inf"):
                loudnorm_stats[key] = 0
            else:
                loudnorm_stats[key] = float(loudnorm_stats[key])
        log.info(f"Данные нормализации: {loudnorm_stats}")
        return loudnorm_stats
    except Exception as e:
        raise Exception(f"Could not parse loudnorm stats; wrong JSON format in string: {e.stderr.decode('utf-8')}")

def apply_normalization(id, audio_file, normalization_data, path_output):
    normalize_file = os.path.join(path_output, str(id) + '_normalize.m4a')
    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-i', audio_file,
            '-af', f'loudnorm=I=-23:TP=-2:LRA=11:measured_I={normalization_data["input_i"]}:measured_LRA={normalization_data["input_lra"]}:measured_TP={normalization_data["input_tp"]}:measured_thresh={normalization_data["input_thresh"]}:offset={normalization_data["target_offset"]}:linear=true:print_format=summary',
            '-c:a', 'aac',
            '-b:a', '320k',
            '-ar', '48000',
            normalize_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return normalize_file
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка при нормализации: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка при нормализации: {e}")    

def avi_copy(id, file_path, path_output):
    avi_file = os.path.join(path_output, str(id) +'_avi.m4v')
    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-i', file_path,
            '-c:v', 'copy',
            '-an',
            avi_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return avi_file
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка конвертации avi в mp4: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка конвертации avi в mp4: {e}")

def copy(id, file_name, file_path, path_output, selected_audio, start_tc, end_tc):
    log = logger(id, file_name)
    copy_file = os.path.join(path_output, str(id) +'.mp4')
    selected_audio = int(selected_audio) - 1
    log.debug(f"start_tc = {start_tc}, end_tc = {end_tc}")
    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-i', file_path,
            '-ss', start_tc,
            '-to', end_tc,
            '-map', '0:v',
            '-map', f'0:a:{selected_audio}',
            '-c:v', 'copy',
            '-c:a', 'copy',
            copy_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return copy_file
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка копирования потока: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка копирования потока: {e}")

def time_format_to_seconds(time_string):
    hours, minutes, seconds = map(float, time_string.split(':'))
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds

def seconds_to_time_format(total_seconds):
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    if seconds >= 59.99:
        seconds = 0
        minutes += 1
        if minutes >= 59.99:
            minutes = 0
            hours += 1

    return f'{hours:02}:{minutes:02}:{seconds:06.3f}'

def create_sub_file(id, file_path, path_output, selected_sub, start_tc, end_tc):
    sub_file = os.path.join(path_output, str(id) + '_sub.ass')
    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-ss', start_tc,
            '-to', end_tc,
            '-i', file_path,
            '-map', f'0:s:{selected_sub}',
            sub_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return sub_file
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка при создание субтитров: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка при создание субтитров: {e}")

def create_srt_file(file_name, file_path, path_output, selected_sub, start_tc, end_tc):

    base_name = os.path.splitext(file_name)[0]
    extension = '.srt'
    srt_file = os.path.join(path_output, base_name + '_SUB' + extension)
    count = 1
    while os.path.exists(srt_file):
        srt_file = os.path.join(path_output, f"{base_name}_SUB_{count}{extension}")
        count += 1

    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-ss', start_tc,
            '-to', end_tc,
            '-i', file_path,
            '-map', f'0:s:{selected_sub}',
            srt_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return srt_file
    
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка при создании субтитров: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка при создании субтитров: {e}")
    
def create_video_file(id, file_path, path_output, start_tc, end_tc, bitrate, infade, outfade, outfade_start, selected_sub, color_space):
    video_file = os.path.join(path_output, str(id) + '_video.m4v')
    filters = f"scale=w=1920:h=1080:force_original_aspect_ratio=1,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setdar=16:9,setsar=1,fade=in:0:d={infade},fade=out:st={outfade_start}:d={outfade}"
    
    if color_space == 'HDR':
        hdr_filters = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
        filters += f",{hdr_filters}"

    if selected_sub >= 0:
        sub_file = create_sub_file(id, file_path, path_output, selected_sub, start_tc, end_tc)
        sub_file = sub_file.replace('/', '\\').replace('\\', '\\\\').replace(':', '\\:')
        filters += f",ass='{sub_file}'"

    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-ss', start_tc,
            '-to', end_tc,
            '-i', file_path,
            '-map', '0:v:0',
            '-c:v', 'h264_nvenc',
            '-preset', 'fast',
            '-profile:v', 'high',
            '-level:v', '4.2',
            '-pix_fmt', 'yuv420p',
            '-b:v', f'{bitrate}',
            '-minrate', f'{bitrate}',
            '-maxrate', f'{bitrate}',
            '-bufsize', f'{bitrate}',
            '-r', '25',
            '-vf', filters,
            '-an',
            video_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка при обработке видео: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка при обработке видео: {e}")

def create_delogo_video_file(id, file_path, path_output, start_tc, end_tc, bitrate, infade, outfade, alpha_mask, square_position, outfade_start, selected_sub, color_space):
    video_file = os.path.join(path_output, str(id) + '_video.m4v')
    x, y, w, h = square_position
    
    filter_complex = (
        f'[0:v:0]delogo=x={x}:y={y}:w={w}:h={h}:show=0[delogo];'
        f'[delogo][1:v]alphamerge, gblur=4[alf];[0:v:0][alf]overlay[v1];'
        f'[v1]scale=w=1920:h=1080:force_original_aspect_ratio=1,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,'
        f'setdar=16:9,setsar=1,fade=in:0:d={infade},fade=out:st={outfade_start}:d={outfade}[v2]'
    )

    if color_space == 'HDR':
        hdr_filters = (
            "zscale=t=linear:npl=100,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
        )
        filter_complex = filter_complex.replace('[v2]', f",{hdr_filters}[v2]")

    if selected_sub >= 0:
        sub_file = create_sub_file(id, file_path, path_output, selected_sub, start_tc, end_tc)
        sub_file = sub_file.replace('/', '\\').replace('\\', '\\\\').replace(':', '\\:')
        filter_complex = filter_complex.replace('[v2]', f",ass='{sub_file}'[v2];")

    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-ss', start_tc,
            '-to', end_tc,
            '-i', file_path,
            '-i', alpha_mask,
            '-c:v', 'h264_nvenc',
            '-preset', 'fast',
            '-profile:v', 'high',
            '-level:v', '4.2',
            '-pix_fmt', 'yuv420p',
            '-b:v', f'{bitrate}',
            '-minrate', f'{bitrate}',
            '-maxrate', f'{bitrate}',
            '-bufsize', f'{bitrate}',
            '-r', '25',
            '-filter_complex', filter_complex,
            '-map', '[v2]',
            '-an',
            video_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка при обработке видео: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка при обработке видео: {e}")

def create_alpha_mask(id, file_path, square_position, path_output):
    output_file_name = os.path.join(path_output, str(id) + '_mask.png')
    x, y, w, h = square_position
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        print("Ошибка открытия видеофайла")
        return
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    black_image = np.zeros((height, width, 3), dtype=np.uint8)
    black_image[y:y+h, x:x+w] = 255
    size = width * height
    thresholds = {
        2100000: 43,
        1400000: 29,
        500000: 15
    }
    blur = next((blur_value for threshold, blur_value in sorted(thresholds.items(), reverse=True) if size > threshold), 7)
    blurred_image = cv2.GaussianBlur(black_image, (blur, blur), 5)
    output_file_path_str = str(output_file_name)
    output_file_path_bytes = output_file_path_str.encode('utf-8')
    with open(output_file_path_bytes, 'wb') as f:
        f.write(cv2.imencode('.png', blurred_image)[1])
    cap.release()

def merge_audio_video(audio_file, video_file, path_output, file_name, nonsub, square_position):
    
    if nonsub == 1 and square_position:
        output_suffix = '_DELOGO_SUB'
    elif nonsub == 1:
        output_suffix = '_SUB'
    elif square_position:
        output_suffix = '_DELOGO'
    else:
        output_suffix = ''
    base_name = os.path.splitext(file_name)[0]
    extension = '.mp4'
    final_output = os.path.join(path_output, base_name + output_suffix + extension)
    count = 1
    while os.path.exists(final_output):
        final_output = os.path.join(path_output, f"{base_name}{output_suffix}_{count}{extension}")
        count += 1

    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-i', video_file,
            '-i', audio_file,
            '-map', '0:v:0',
            '-map', '1:a',
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-map_metadata', '-1',
            final_output
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    except subprocess.CalledProcessError as e:
        raise Exception(f"Ошибка при создании финального файла: {e.stderr.decode('utf-8')}")
    except Exception as e:
        raise Exception(f"Ошибка при создании финального файла: {e}")

    return final_output

def audio_pipeline(id, file_path, file_name, selected_audio, path_output, start_tc, end_tc, infade, outfade, outfade_start, audio_queue):
    log = logger(id, file_name)
    try:
        audio_file = audio_encode(id, file_path, selected_audio, path_output, start_tc, end_tc, infade, outfade, outfade_start)
        log.debug(f"Конвертация в стерео успешно завершена.")
        normalize_file = os.path.join(path_output, str(id) + '_normalize.m4a')
        normalization_data = extract_normalization_data(id, file_name, audio_file)
        apply_normalization(id, audio_file, normalization_data, path_output)
        log.debug(f"Нормализация успешно завершена.")
        os.remove(audio_file)
        audio_queue.put(normalize_file)
    except Exception as e:
        log.error(f"{e}")
        audio_queue.put(None)

def video_pipeline(id, file_path, file_name, path_output, start_tc, end_tc, bitrate, infade, outfade, square_position, selected_sub, outfade_start, srt, color_space, video_queue):
    log = logger(id, file_name)
    try:
        if file_path.lower().endswith('.avi'):
            avi_file = os.path.join(path_output, str(id) +'_avi.m4v')
            avi_copy(id, file_path, path_output)
            file_path = avi_file

        video_file = os.path.join(path_output, str(id) + '_video.m4v')
        
        try:
            if not square_position:
                create_video_file(id, file_path, path_output, start_tc, end_tc, bitrate, infade, outfade, outfade_start, selected_sub, color_space)
            else:
                square_position = eval(square_position)
                alpha_mask = os.path.join(path_output, str(id) + '_mask.png')
                create_alpha_mask(id, file_path, square_position, path_output)
                create_delogo_video_file(id, file_path, path_output, start_tc, end_tc, bitrate, infade, outfade, alpha_mask, square_position, outfade_start, selected_sub, color_space)
                os.remove(alpha_mask)
            log.debug(f"Конвертация видео успешно завершена.")
            
        except Exception as e:
            log.error(f"{e}")
            video_queue.put(None)
            return
        
        sub_file = os.path.join(path_output, str(id) + '_sub.ass')
        if os.path.isfile(sub_file):
            os.remove(sub_file)
        
        if srt == 1:
            try:
                sufix = "_SUB"
                if square_position:
                    sufix = "_DELOGO_SUB"
                final_name = os.path.join(path_output, os.path.splitext(file_name)[0] + sufix + '.srt')
                srt_file = create_srt_file(file_name, file_path, path_output, selected_sub, start_tc, end_tc)
                os.rename(srt_file, final_name)
                
                log.debug(f"SRT файл успешно создан для {file_name}")
                
            except Exception as e:
                raise Exception(f"Ошибка при создании SRT файла: {e}")
            
        video_queue.put(video_file)

    except Exception as e:
        log.error(f"{e}")
        video_queue.put(None)

def process_files(id):
    normalize_file = None
    video_file = None
    
    conn = create_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_name, file_path, file_path_to_output, start_tc, end_tc, minus, infade, outfade, square_position, selected_preset, color_space, selected_audio, selected_sub, srt, nonsub
        FROM media_info
        WHERE id = ?
    ''', (id,))
    info = cursor.fetchone()   
    
    file_name, file_path, path_output, start_tc, end_tc, minus, infade, outfade, square_position, selected_preset, color_space, selected_audio, selected_sub, srt, nonsub = info
    selected_sub -= 1
    out_f = time_format_to_seconds(end_tc)
    if minus != "00:00:00.000":
        conv_minus = time_format_to_seconds(minus)
        out_f -= conv_minus
        end_tc = seconds_to_time_format(out_f)
    outfade_start = str(out_f - float(outfade))
    
    log = logger(id, file_name)
    log.debug(f"Обработка файла: {file_name}")
    
    try:
        # Если пресет 10 Mbps и 6 Mbps
        if selected_preset == "10 Mbps" or selected_preset == "6 Mbps":
            if selected_preset == "10 Mbps":
                bitrate = "10000k"
            elif selected_preset == "6 Mbps":
                bitrate = "6000k"

            audio_queue = multiprocessing.Queue()
            video_queue = multiprocessing.Queue()
            
            audio_process = multiprocessing.Process(target=audio_pipeline, args=(id, file_path, file_name, selected_audio, path_output, start_tc, end_tc, infade, outfade, outfade_start, audio_queue))
            video_process = multiprocessing.Process(target=video_pipeline, args=(id, file_path, file_name, path_output, start_tc, end_tc, bitrate, infade, outfade, square_position, selected_sub, outfade_start, srt, color_space, video_queue))
            
            audio_process.start()
            video_process.start()

            audio_process.join()
            video_process.join()

            normalize_file = audio_queue.get()
            video_file = video_queue.get()

            log.debug(f"Аудиофайл: {normalize_file}")
            log.debug(f"Видеофайл: {video_file}")

            if not video_file or not normalize_file:
                missing_file = "Видеофайл" if not video_file else "Аудиофайл"
                raise Exception(f"Не удалось создать {missing_file}")
            
            try:
                final_output = merge_audio_video(normalize_file, video_file, path_output, file_name, nonsub, square_position)
                log.debug(f"Файлы успешно объединены в {final_output}")

                if nonsub == 1:
                    selected_sub, srt, nonsub = -1, 0, 0
                    video_process = multiprocessing.Process(target=video_pipeline, args=(id, file_path, file_name, path_output, start_tc, end_tc, bitrate, infade, outfade, square_position, selected_sub, outfade_start, srt, color_space, video_queue))
                    video_process.start()
                    video_process.join()
                    new_video_file = video_queue.get()

                    if not new_video_file:
                        raise Exception(f"Не удалось создать новый видеофайл для {file_name}")

                    final_output_no_sub = merge_audio_video(normalize_file, new_video_file, path_output, file_name, nonsub, square_position)
                    log.debug(f"Файлы успешно объединены в {final_output_no_sub}")

                status = 'Done'
                cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
                conn.commit()

            except Exception as e:
                status = 'Error'
                cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
                conn.commit()
                raise Exception(f"Ошибка при сшивании файлов: {e}")

        # Если пресет AAC
        elif selected_preset == "AAC":
            try:      
                audio_queue = multiprocessing.Queue()
                audio_process = multiprocessing.Process(target=audio_pipeline, args=(id, file_path, file_name, selected_audio, path_output, start_tc, end_tc, infade, outfade, outfade_start, audio_queue))
                audio_process.start()
                audio_process.join()

                normalize_file = audio_queue.get()
                log.debug(f"Аудиофайл: {normalize_file}")

                if not normalize_file:
                    raise Exception(f"Не удалось создать аудиофайл для {file_name}")

                final_name = os.path.join(path_output, os.path.splitext(file_name)[0] + '_AAC.m4a')
                count = 1
                while os.path.exists(final_name):
                    final_name = os.path.join(path_output, os.path.splitext(file_name)[0] + f'_AAC_{count}.m4a')
                    count += 1
                os.rename(normalize_file, final_name)
                
                log.debug(f"Финальный файл: {final_name}")
                status = 'Done'
                cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
                conn.commit()
                
            except Exception as e:
                status = 'Error'
                cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
                conn.commit()
                raise Exception(f"Ошибка при выводе аудио: {e}")
            
        # Если пресет COPY
        elif selected_preset == "COPY":
            try:
                copy_file = copy(id, file_name, file_path, path_output, selected_audio, start_tc, end_tc)
                
                final_name = os.path.join(path_output, os.path.splitext(file_name)[0] + '.mp4')
                count = 1
                while os.path.exists(final_name):
                    final_name = os.path.join(path_output, os.path.splitext(file_name)[0] + f'_{count}.mp4')
                    count += 1
                os.rename(copy_file, final_name)
                
                log.debug(f"Файл успешно скопирован: {final_name}")
                status = 'Done'
                cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
                conn.commit()
                
            except Exception as e:
                status = 'Error'
                cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
                conn.commit()
                raise Exception(f"Ошибка при копировании файла: {e}")

        # Если пресет SRT
        elif selected_preset == "SRT":
            try:
                srt_file = create_srt_file(file_name, file_path, path_output, selected_sub, start_tc, end_tc)
                
                # final_name = os.path.join(path_output, os.path.splitext(file_name)[0] + '_SUB.srt')
                # count = 1
                # while os.path.exists(final_name):
                #     final_name = os.path.join(path_output, os.path.splitext(file_name)[0] + f'_SUB_{count}.srt')
                #     count += 1
                # os.rename(srt_file, final_name)
                
                log.debug(f"SRT файл успешно создан: {srt_file}")
                status = 'Done'
                cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
                conn.commit()
                
            except Exception as e:
                status = 'Error'
                cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
                conn.commit()
                raise Exception(f"Ошибка при создании SRT файла: {e}")

    except Exception as e:
        status = 'Error'
        cursor.execute('UPDATE media_info SET status = ? WHERE id = ?', (status, id))
        conn.commit()
        raise Exception(f"Ошибка: {e}")

    finally:
        # Удаление промежуточных файлов
        if normalize_file and os.path.exists(normalize_file):
            os.remove(normalize_file)
        if video_file and os.path.exists(video_file):
            os.remove(video_file)

        # Завершение логирования
        log.debug("Процесс обработки завершён.")
        logging.shutdown()
        conn.close()
        time.sleep(2)
