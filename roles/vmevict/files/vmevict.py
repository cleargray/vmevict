#!/usr/bin/env python3

import sys, os, yaml, logging, time
from systemd import journal
"""
Invoke logger settings
"""

logger = logging.getLogger('upstream_check script')
hdlr = journal.JournalHandler()
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)

"""
Path to memory.stat file
"""
memory_stat_file = "/sys/fs/cgroup/memory/memory.stat"

"""
Functions
"""

def read_config(config_path):
    """
    Reading config .yaml file
    """
    config_yaml = yaml.safe_load(open(config_path))
    if config_yaml and config_yaml is not None:
        return config_yaml
    else:
        logger.error("Cant't read config from %s", config_path)
        return False
    

def file_path_checker(path_list):
    """
    Get absolute path to file. If dir -- get all subfiles recursively
    """
    file_list = []
    for path in path_list:
        if os.path.isfile(path):
            file_list.append(path)
            logger.debug("File list on %s: %s", path, file_list)
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_list.append(file_path)
        else:
            logger.warning("This file path is unknown: %s", path)
    logger.debug("File list: %s", file_list)
    return file_list


def config_parser(config_path):
    """
    Parsing config file and generate config dict for use
    """
    config = read_config(config_path)
    if config:
        config_list = dict()
        if 'EvictFiles' in config.keys():
            [*config_list['evict_file_list']] = config['EvictFiles']
        if 'EvictTresholdPercentile' or 'EvictTresholdSize' in config.keys():
            config_list['evict_memory_perc'] = config['EvictTresholdPercentile']
        else:
            config_list['evict_memory_perc'] = False
        if 'EvictTresholdSize' in config.keys():
            config_list['evict_memory_size'] = config['EvictTresholdSize']
        else:
            config_list['evict_memory_size'] = False
        if 'EnableDebug' in config.keys():
            config_list['enable_debug'] = config['EnableDebug']
        if 'CheckInterval' in config.keys():
            config_list['check_interval'] = config['CheckInterval']
        if config_list:
            logger.info("Configuration from %s loaded.", config_path)
            logger.debug("Result config: %s", config_list)
            return config_list
        else:
            logger.error("Configuration not loaded.")
            return False
    else:
        logger.error("Configuration not loaded.")
        return False        


def get_memory_stats(memory_stat_file):
    """
    Parsing memory.stat file into yaml dict for usage
    """
    memory_stat_string = str()
    memory_stat_yaml = dict()
    with open(memory_stat_file) as memory_stat:
        memory_stat_read = memory_stat.read()
        if memory_stat_read and memory_stat_read is not None:
            for line in memory_stat_read:
                yaml_line = line.replace(' ', ': ')
                memory_stat_string += yaml_line
            memory_stat_yaml = yaml.load(memory_stat_string)
            logger.debug("Yaml array with memory stats: %s", memory_stat_yaml)
            logger.info("Memory stats collected")
            return memory_stat_yaml
        else:
            logger.error("memory.stats file is empty or doesn`t exist.")
            return False

def convert_bytes(num):
    """
    Convert bytes to MB GB etc
    """
    for x in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0


if __name__ == "__main__":
    if len(sys.argv) == 2:
        config_path = sys.argv[1]
    else:
        print("Provide config file path into script arguments")
        sys.exit(-1)

    config_dict = config_parser(config_path)
    if not config_dict:
        logger.error("Problem with config loading. Exit.")
        sys.exit(-1)
    
    if config_dict['enable_debug']:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    logger.debug("Config: %s", config_dict)

    if config_dict['check_interval']:
        interval = config_dict['check_interval']
        logger.debug("Checking interval is %s", interval)
    else:
        interval = 60
        logger.debug("Checking interval is not set. Use default: %s", interval)

    if config_dict['evict_memory_perc']:
        memory_percentage = config_dict['evict_memory_perc']
        logger.debug("Mem percentage: %s", memory_percentage)
    else:
        memory_percentage = 1
        logger.debug("Overide not configured memory_percentage to 100%", memory_percentage)
    if config_dict['evict_memory_size']:
        memory_size = config_dict['evict_memory_size']
        logger.debug("Mem size: %s", memory_size)
    else:
        memory_size = 0
    if not memory_percentage and not memory_size:
        logger.error("None of eviction thresholds are set. Exit.")
        sys.exit(-1)
    if config_dict['evict_file_list']:
        evict_file_list = config_dict['evict_file_list']
        logger.debug("Files for eviction: %s", evict_file_list)
    else:
        logger.error("Files for eviction not specified. Exit.")
        sys.exit(-1)

    while True:       
        memory_dict = get_memory_stats(memory_stat_file)
        if not memory_dict:
            logger.error("Problem with memory stats collecting. Exit.")
            sys.exit(-1)
        memory_limit = memory_dict['hierarchical_memory_limit']
        logger.debug("Cgroup memory limit: %s", memory_limit)
        total_active_file = memory_dict['total_active_file']
        logger.debug("Total_active_file: %s", total_active_file)
        total_inactive_file = memory_dict['total_inactive_file']
        logger.debug("Total_inactive_file: %s", total_inactive_file)
        sum_cache_size = total_active_file + total_inactive_file
        logger.debug("sum_cache_size: %s", sum_cache_size)
        cache_percentile = float(sum_cache_size) /float(memory_limit)
        logger.debug("Real cache percentile: %s", cache_percentile)
        
        file_list = file_path_checker(evict_file_list)
        logger.debug("Full list of files for eviction: %s", file_list)

        if memory_size == 0:
            memory_size = memory_limit
            logger.debug("Overide not configured memory_size to memory_limit: %s", memory_size)

        if (float(cache_percentile) >= float(memory_percentage)) or (sum_cache_size >= memory_size):
            logger.info("One of treshold has been achieved.")
            for file in file_list:
                try:
                    fd = os.open(file, os.O_RDWR)
                    logger.debug("File evicting: %s", file)
                    start_position = os.lseek(fd, 0, 0)
                    logger.debug("Start file pozition: %s", start_position)
                    end_position = os.lseek(fd, 2, 2)
                    logger.debug("End file pozition: %s", end_position)
                    size = convert_bytes(end_position)
                    logger.info("Trying to evict %s from %s caches", size, file)
                    os.fdatasync(fd)
                    os.posix_fadvise(fd, start_position, end_position, os.POSIX_FADV_DONTNEED)
                    logger.info("Eviction of %s successful",file)
                    logger.debug("Closing fd after eviction")
                    os.close(fd)
                except Exception as err:
                    logger.warning("Couldn`t evict file %s because of %s", file, err)
            logger.info("Eviction finished.")
        time.sleep(interval)