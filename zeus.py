#!/usr/bin/python3
import contextlib
import json
import logging
import socket
import subprocess
import time
import uuid

import click
import fluent.handler

from boards import RPi
import lib.atsio
import lib.video_stream_validator

FFMPEG = lib.video_stream_validator.FFmpegWrapper()

# NOTE
# See Instruction and overview of this test at 
# https://teknique.jira.com/l/cp/0m4rixuQ

# Use different titles for separating FA test result for different clients
TITLE='Zeus'
TITLE_SHORT='zeus'
# DTS that should be used
DTS='Oclea CV25 Zeus'

# Add Serial Number to all log messages
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(serial_number)s - %(message)s')

SERIAL_NUMBER = ''
old_factory = logging.getLogRecordFactory()

def record_factory(*args, **kwargs):
    global SERIAL_NUMBER
    record = old_factory(*args, **kwargs)
    record.serial_number = SERIAL_NUMBER
    return record
logging.setLogRecordFactory(record_factory)

# Setup root logger
LOGGER = logging.getLogger()
LOGGER.setLevel(level=logging.DEBUG)

# NOTE. Consider adding a sqlite python handler
# https://github.com/ar4s/python-sqlite-logging/blob/master/sqlite_handler.py
file_handler = logging.handlers.WatchedFileHandler(f'{socket.gethostname()}_{TITLE_SHORT}_device_log', mode='a')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)


LOGGER.addHandler(file_handler)
LOGGER.addHandler(console_handler)


@click.command()
def run():
    global SERIAL_NUMBER
    click.clear()
    failed_on = []
    version = '2.2.0'
    leds = {
        'RED': 0,
        'GREEN': 1,
        'BLUE': 2,
    }
    device = RPi.device
    # To make it slightly faster at the start
    device.power_off_period=3
    device.power_reboot()

    # Overwriting enter_ambausb mode with cli.
    # Originally this function is now aware that it's runnin on a CLI context
    # (and it shouldn't).  Since the reset/amba button won't be soldered, the
    # only way to enter in ambausb mode is to manually press the physical
    # buttons.
    def enter_ambausb_mode(*args, **kwargs):
        while not device.in_ambausb_mode:
            LOGGER.info(
                '\n\n\n'
                'Please set the device to AmbaUSB mode by holding the amba '
                'button (the one closer to the usb cable) then pressing the '
                'other boot button then releasing the amba button.'
            )
            click.pause()
    device.enter_ambausb_mode = enter_ambausb_mode

    LOGGER.info(f'Starting tests for {TITLE}!\n\n\n')

    LOGGER.info('1st test is to check if the device can be flashed.')
    LOGGER.info(f'Updating firmware to version {version}...')
    try:
        RPi.update_firmware(version, released=False, is_yocto=True)
        # Double-check we are on the right DTS
        assert device.oclea_info['dts-model'].strip() == f'{DTS}'
        LOGGER.info(f'Firmware test result -> PASSED.\n\n')
    except:
        LOGGER.exception(f'Firmware test result -> FAILED.\n\n')
        failed_on.append('firmware upgrade')
    device.ensure_ready()
    device.setup_bootstrap()
    SERIAL_NUMBER = device.serial_number
    LOGGER.info(f'HELLO from {SERIAL_NUMBER}!')

    LOGGER.info('\n\n\n2nd test is to check if the leds are working.')
    # Turn off all leds
    for led in leds.values():
        device.set_led_state(led, 'off')

    led_results = []
    for led_name, led in leds.items():
        device.set_led_state(led, 'on')
        result = ''
        while result not in ['y', 'n']:
            LOGGER.info(f'Is the {led_name} led on? [yn]')
            result = click.getchar()
            LOGGER.info(result)
        led_results.append(result)
        device.set_led_state(led, 'off')
    if 'n' in led_results:
        failed_on.append('led')
    LOGGER.info(f'{SERIAL_NUMBER} LED test result -> {result}\n\n')
    msg = '\n\nFinished interactive tests.  Time to assemble another unit.\n\n'
    LOGGER.info(msg)

    LOGGER.info('3rd test is to check if the device detects i2c.')
    # Expected i2c result
    # [root@Oclea ~]# i2cdetect -y 0
    #      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
    # 00:          -- -- -- -- -- -- -- -- -- -- -- -- --
    # 10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 70: -- -- -- -- -- -- -- --
    # [root@Oclea ~]# i2cdetect -y 1
    #      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
    # 00:          -- -- -- -- -- -- -- -- -- -- -- -- --
    # 10: -- -- -- -- -- -- -- -- -- -- UU -- -- -- -- --
    # 20: UU -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 40: -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- --
    # 50: UU -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 60: -- -- -- -- -- -- -- -- -- UU -- -- -- -- -- --
    # 70: -- -- -- UU -- -- -- --
    # [root@Oclea ~]# i2cdetect -y 2
    #      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
    # 00:          -- -- -- -- -- -- -- -- -- -- -- -- --
    # 10: -- -- UU -- -- -- -- -- -- -- -- -- -- -- -- --
    # 20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 30: 30 -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # 70: -- -- -- -- -- -- -- --
    # i2cdetect -y 20
    #      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
    # 00:          -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 10: -- -- -- -- -- -- -- -- -- -- UU -- -- -- -- -- 
    # 20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 30: -- -- -- -- -- -- 36 -- -- -- -- -- -- -- -- -- 
    # 40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 60: -- -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- 
    # 70: -- -- -- UU -- -- -- --                         
    # [root@zeus-000LF ~]# i2cdetect -y 20
    #      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
    # 00:          -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 20: UU -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 40: -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- -- 
    # 50: UU -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 60: -- -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- 
    # 70: -- -- -- UU -- -- -- --                         
    # [root@zeus-000LF ~]# i2cdetect -y 21
    #      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
    # 00:          -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 60: -- -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- 
    # 70: -- -- -- UU -- -- -- --                         
    # [root@zeus-000LF ~]# i2cdetect -y 22
    #      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
    # 00:          -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
    # 60: -- -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- 
    # 70: -- -- -- UU -- -- -- --                         
    i2c_result = True
    total_dash = 13 + 16*6 + 8   # Total number of -- expected in an output
    # Expecting only 5 on 'bus 01' because 1a does not show always.
    bus_addrs = [0, 1, 2, 20, 21, 22, 23]
    expected_dev_count = [0, 5, 2, 4, 5, 2, 2]
    for addr, dev_count in zip(bus_addrs, expected_dev_count):
        # Retry up to 3 times if i2cdetect result is not what we expected
        for retry_count in range(3):
            found_all_i2c_dev = True
            out = device.send_command(f'i2cdetect -y {addr}')
            LOGGER.info(out)
            found = total_dash - out.count('--') 
            if found < dev_count:
                found_all_i2c_dev = False
            if found_all_i2c_dev:
                break
            time.sleep(2)
        else:
            i2c_result = False
    i2c_result = 'PASSED' if i2c_result else 'FAILED'
    if i2c_result == 'FAILED':
        failed_on.append('i2c readings')
    LOGGER.info(f'{SERIAL_NUMBER} I2c test result -> {i2c_result}.\n\n')

    LOGGER.info('4th test is a simple check for current/voltage/power.')
    atsio = lib.atsio.Atsio()
    for _ in range(5):
        LOGGER.info(f'IDLE {atsio.get_i2c_readings()}')
    # NOTE. Add basic check from the data from the last time?
    # max,      median  min
    # 4.67      4.17    1.53
    # Consider using average of these values for better test stability
    # Consider using voltage or current if that helps us better validate the devices
    LOGGER.info(f'{SERIAL_NUMBER} Power test result -> PASSED\n\n')

    duration = 120
    slack = 20
    fn = f'{TITLE_SHORT}_{SERIAL_NUMBER}.mp4'
    blackdetect_fn = f'{TITLE_SHORT}_{SERIAL_NUMBER}_blackdetect.mp4'
    blackdetect_duration = 10
    LOGGER.info(f'5th test is to check the streaming for {duration}s (2 min).')
    # Start streaming if we could retrieve DUT IP
    try:
        ip = None
        with contextlib.suppress(EnvironmentError):
            ip = device.wait_for_ip()

        if not ip:
            LOGGER.info("Device failed to get an valid IP")
            failed_on.append('Getting IP')
        else:
            # using 4k with imx327 does not result in fail to start at 'oclea_rtsp_example -r'
            # That is a bit strange since it used to
            # It results in 503 service unavailable when trying to stream
            width, height = device.max_resolution
            pipeline = f'oclea_rtsp_example -s -w {width} -h {height}'
            url = f'rtsp://{ip}:8554/test'
            validator = lib.video_stream_validator.VideoStreamValidator(
                url, LOGGER)
            with device.start_stream_in_bg(pipeline):

                # First record 10 seconds video to detect black screen
                validator.launch_ffmpeg(
                    blackdetect_duration, blackdetect_fn, extra_args='-strict -2')
                validator.ffmpeg.wait_for_start(
                    validator.ffmpeg_console_log, blackdetect_duration*2)
                time.sleep(blackdetect_duration)
                validator.validate_stream_termination(blackdetect_duration*2)

                LOGGER.info(f'Preparing video stream at {url}')
                validator.launch_ffmpeg(
                    duration + slack, fn, extra_args='-strict -2')
                validator.ffmpeg.wait_for_start(
                    validator.ffmpeg_console_log, slack)
                LOGGER.info('Stream started.')
                timeout = time.time() + duration
                temperatures = []
                power_in_watts = []
                while time.time() < timeout:
                    temperature = device.get_temperature()
                    temperatures.append(temperature)
                    reading = atsio.get_i2c_readings()
                    power_in_watts.append(reading['DUT DC Power (W)'])
                    LOGGER.info(f'STREAMING {reading}')
                    LOGGER.info(f'Current temperature: {temperature}C')
                validator.validate_stream_termination(slack)
            LOGGER.info('Stream ended.')
            avg_temp = round(sum(temperatures) / len(temperatures), 2)
            avg_power = round(sum(power_in_watts) / len(power_in_watts), 2)
            LOGGER.info(f'{SERIAL_NUMBER} Max temperature: {max(temperatures)}C')
            LOGGER.info(f'{SERIAL_NUMBER} Avg temperature: {avg_temp}C')
            LOGGER.info(f'{SERIAL_NUMBER} Min temperature: {min(temperatures)}C')
            LOGGER.info(f'{SERIAL_NUMBER} Avg DC Power (Watts): {avg_power}')
            power_check_result = 'PASSED'
            # Choose 4.3 because 4.25 was the max of ~100 Jnaus units processed in
            # Oct 2022. Let's use it for now as a start and fine-tune from there.
            # Update: Power usage can depend on sensor type, streaming resolution and SOM type.
            # From a quick chat with Yufei, Zeus should consume about 4W
            # (5V x 0.8A) whereas Janus ~3W (5V x 0.6A). But then streaming
            # resolution and sensor should also make a bit of difference.
            if avg_power > 4.3:
                power_check_result = 'FAILED'
                failed_on.append('DUT Power during streaming')
            LOGGER.info(
                f'{SERIAL_NUMBER} DUT Power during streaming -> {power_check_result}.\n\n')
            # Data from the last time (July 2021),
            # Max temp readings
            # Max: 60.96 Median: 51.305
            # Avg temp readings
            # Max: 57.03 Median: 46.32
            # Min temp readings
            # Max: 50.6 Median: 38.8
            # Give a warning instead of failing the test because
            # DUT temperature could be high from repetitive testing.
            if max(temperatures) > 60:
                LOGGER.warning(
                    f'{SERIAL_NUMBER} Temperature is quite high '
                    'after streaming (over 60 degC).'
                    '\n\n')

            info = subprocess.check_output(['exiftool', '-json', fn])
            info = json.loads(info)[0]
            image_size = info['ImageSize']
            fps = info['VideoFrameRate']
            LOGGER.info(
                f"{SERIAL_NUMBER} Record info: {image_size} @ {fps} fps."
                f"  {info['FileSize']}")
            # NOTE: Recording tests may fail several ways
            #
            # 1. FFMPEG exiting early
            #      lib.video_stream_validator.ExitedEarlyError:
            #      FFmpeg process exited early with 1.
            #      -  libavfilter     7. 40.101 /  7. 40.101
            #      -  libavresample   4.  0.  0 /  4.  0.  0
            #      -  libswscale      5.  3.100 /  5.  3.100
            #      -  libswresample   3.  3.100 /  3.  3.100
            #      -  libpostproc    55.  3.100 / 55.  3.100
            #      -Routing option strict to both codec and muxer layer
            #      -[tcp @ 0x14fa210] Starting connection attempt to 172.16.3.157 port 8554
            #      -[tcp @ 0x14fa210] Connected attempt failed: Network is unreachable
            #      -[tcp @ 0x14fa210] Connection to tcp://172.16.3.157:8554?timeout=0 failed: Network is unreachable
            #      -rtsp://172.16.3.157:8554/test: Network is unreachable
            # 2.  Timeout waiting for keywords at start up
            #       TimeoutError: Waiting to find for ['loop start now'] in /mnt/media/1648427090_temp_streaming_log.
            #       -Contents: Script started on 2022-03-28 00:24:49+00:00 [<not executed on terminal>]
            #       -WARNING: no real random source present!
            #       -stream ready at rtsp://127.0.0.1:8554/test


            fps_check = black_screen_check = 'passed'
            if fps < 29 or image_size != f'{width}x{height}':
                failed_on.append('FPS and resolution check')
                fps_check = 'failed'
            LOGGER.info(
                f'{SERIAL_NUMBER} FPS & resolution test -> {fps_check}.\n\n')

            # Lower pic_th to 0.8 from default 0.98 since there is a tiny
            # hole on the lens cover. This combination of values were found
            # through testings.
            black_duration = FFMPEG.black_detect_from_file(
                                blackdetect_fn, blackdetect_duration*2,
                                duration_th=0, pix_th=0.1, pic_th=0.8)
            if black_duration >= 0.3:
                failed_on.append('black screen detection')
                black_screen_check = (
                    'fail. Make sure lens cover is taken off and retry')
            LOGGER.info(
                f'{SERIAL_NUMBER} black screen detection test -> '
                f'{black_screen_check}.\n\n')

    except Exception:
        LOGGER.exception(f"{SERIAL_NUMBER} ran into exception during streaming")
        failed_on.append('recording')

    LOGGER.info('\n\n\n')
    LOGGER.info('Here is the end of the tests.  Time to connect another device')
    LOGGER.info(f'Mark the device with its serial number: {SERIAL_NUMBER[-5:]}.')
    if failed_on:
        LOGGER.error('\n\n#################################################')
        LOGGER.error('# Detected a failure.  Please set device aside. #')
        LOGGER.error('#################################################')
        LOGGER.error('\n')
        LOGGER.error(f'{SERIAL_NUMBER} failed on: {failed_on}')
    else:
        device.send_command('rm ~/nohup.out /mnt/media/*_temp_streaming_log ~/.bash_history; history -c')
    device.cut_power()
    click.pause()


if __name__ == '__main__':
    run()
