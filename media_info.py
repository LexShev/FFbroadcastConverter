import ffmpeg
import sqlite3
import os

def get_media_info(file_path):
    """Получить информацию о медиафайле с помощью ffprobe."""
    try:
        probe = ffmpeg.probe(file_path)
        return probe
    except ffmpeg.Error as e:
        print(f"Ошибка при получении информации о файле: {e}")
        return None

def format_duration(duration):
    """Преобразовать значение длительности в формат HH:MM:SS.SSS"""
    hours = int(duration // 3600)
    minutes = int((duration % 3600) // 60)
    seconds = duration % 60
    return f"{hours:02}:{minutes:02}:{seconds:06.3f}"

def insert_media_info(db_path, file_path, tab):
    """Вставить информацию о медиафайле и дорожках в базу данных."""
    info = get_media_info(file_path)
    if info is None:
        print(f"Не удалось получить информацию о файле: {file_path}")
        return
    
    format_info = info['format']
    streams_info = info['streams']
    video_info = next((stream for stream in streams_info if stream['codec_type'] == 'video'), None)
    fps = eval(video_info['r_frame_rate']) if video_info and 'r_frame_rate' in video_info else None
    video_codec = video_info.get('codec_name') if video_info else None
    display_aspect_ratio = video_info.get('display_aspect_ratio') if video_info else None
    scan_type = video_info.get('field_order') if video_info else None
    bit_depth = video_info.get('bits_per_raw_sample') if video_info else None
    color_space = determine_hdr_or_sdr(video_info)
    resolution = f"{video_info['width']}x{video_info['height']}" if video_info else None
    audio_tracks = [stream for stream in streams_info if stream['codec_type'] == 'audio']
    sub_tracks = [stream for stream in streams_info if stream['codec_type'] == 'subtitle']

    num_audio_tracks = len(audio_tracks)
    num_sub_tracks = len(sub_tracks)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    file_name = os.path.basename(file_path)
    directory_path = os.path.dirname(file_path)
    file_path_to_output = directory_path
    
    cursor.execute('''
        INSERT INTO media_info (
            file_name, directory_path, file_path, file_path_to_output, format_name, duration,
            start_tc, end_tc, minus, infade, outfade, selected_preset, square_position,
            size, bit_rate, fps, video_codec, display_aspect_ratio, scan_type,
            bit_depth, color_space, resolution, status, selected_audio, selected_sub,
            num_audio_tracks, num_sub_tracks, srt, tab, nonsub
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        file_name,
        directory_path,
        file_path,
        file_path_to_output,
        format_info.get('format_name'),
        format_duration(float(format_info.get('duration', 0))),
        '00:00:00.000',  
        format_duration(float(format_info.get('duration', 0))),
        '00:00:00.000',
        0,
        0,
        '10 Mbps',
        '',
        int(format_info.get('size', 0)),
        int(format_info.get('bit_rate', 0)),
        fps,
        video_codec,
        display_aspect_ratio,
        scan_type,
        bit_depth,
        color_space,
        resolution,
        'Ready',
        1,
        0,
        num_audio_tracks,
        num_sub_tracks,
        0,
        int(tab),
        0
    ))
    
    media_info_id = cursor.lastrowid
    for idx, stream in enumerate(audio_tracks):
        duration = float(stream.get('duration', format_info.get('duration', 0)))
        cursor.execute('''
            INSERT INTO audio_tracks (
                media_info_id, track_number, codec_name, handler_name, duration, bit_rate, channels, sample_rate, language, title, stream_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            media_info_id,
            idx + 1,
            stream.get('codec_name'),
            stream.get('tags', {}).get('handler_name', 'unknown'),
            format_duration(duration),
            int(stream.get('bit_rate', 0)),
            int(stream.get('channels', 0)),
            int(stream.get('sample_rate', 0)),
            stream.get('tags', {}).get('language', 'unknown'),
            stream.get('tags', {}).get('title', 'unknown'),
            stream.get('index')
        ))

    for idx, stream in enumerate(sub_tracks):
        is_forced = stream.get('disposition', {}).get('forced', 0)
        forc = '(forced)' if is_forced else ''
        cursor.execute('''
            INSERT INTO sub_tracks (
                media_info_id, track_number, codec_name, language, title, forc
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            media_info_id,
            idx + 1,
            stream.get('codec_name'),
            stream.get('tags', {}).get('language', 'unknown'),
            stream.get('tags', {}).get('title', 'unknown'),
            forc
        ))
    
    conn.commit()
    conn.close()

def determine_hdr_or_sdr(video_info):
    """Определить, является ли видео HDR или SDR."""
    if not video_info:
        return 'unknown'

    color_primaries = video_info.get('color_primaries')
    transfer_characteristics = video_info.get('color_transfer')
    # matrix_coefficients = video_info.get('color_space')

    if color_primaries == 'bt2020' and transfer_characteristics == 'smpte2084':
        return 'HDR'
    elif color_primaries == 'bt709' and transfer_characteristics == 'bt709':
        return 'SDR'
    
    return 'SDR'

