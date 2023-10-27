import ingest as ingest_func
from pathlib import Path
import re

import os


def sort_files(file_array):
    most_popular = []
    rest_netdata_integrations = []
    community_integrations = []

    for file in file_array:
        if Path(file).is_file():
            # [filename, filepath, banner message, banner color]
            content = Path(file).read_text()
            
            if "most_popular: \"True\"" in content:
                most_popular.append(
                    [str(file).lower().rsplit("/", 1)[1], file, "by Netdata",  "#00ab44"])
            elif "maintained%20by-Netdata-" in content:
                rest_netdata_integrations.append(
                    [str(file).lower().rsplit("/", 1)[1], file, "by Netdata", "#00ab44"])
            else:
                community_integrations.append(
                    [str(file).lower().rsplit("/", 1)[1], file, "by Community", "rgba(0, 0, 0, 0.25)"])

    sorted_array = sorted(
        most_popular) + sorted(rest_netdata_integrations) + sorted(community_integrations)

    return sorted_array


def get_dir_make_file_and_recurse(directory):

    path, name = str(directory).rsplit("/", 1)
    filename = f"{path}/{name}/{name}.mdx"

    # Do stuff for all the files inside the dict
    if len(sorted(Path(directory).glob("**/**/*"))) > 1:
        # print(directory)

        sorted_list = sort_files(Path(directory).glob("**/**/*"))

        try:
            sidebar_position = re.search(
                r'sidebar_position:.*', Path(sorted_list[0][1]).read_text())[0]
        except TypeError:
            sidebar_position = ""

        sidebar_label = str(directory).rsplit("/", 1)[1]

        if "data-collection" in str(directory):
            sidebar_position = ""

        if "centralized-cloud-notifications" in sidebar_label:
            sidebar_label = "Centralized Cloud Notifications"
        elif "agent-dispatched-notifications" in sidebar_label:
            sidebar_label = "Agent Dispatched Notifications"
        elif sidebar_label == "notifications":
            sidebar_label = "Notifications"
        elif sidebar_label == "exporting":
            sidebar_label = "Exporting"

        md = \
            f"""---
sidebar_label: "{sidebar_label}"
{sidebar_position}
hide_table_of_contents: true
learn_status: "AUTOGENERATED"
slug: "{ingest_func.clean_and_lower_string(str(directory)).split('docs',1)[1]}"
learn_link: "https://learn.netdata.cloud/{ingest_func.clean_and_lower_string(str(directory))}"
---

# {sidebar_label}

import \u007b Grid, Box \u007d from '@site/src/components/Grid_integrations';

<Grid  columns="4">
"""

        # TODO CHANGE
        sorted_list = sort_files(Path(directory).glob("**/**/*"))

        # print(sorted_list)
        # quit()

        for file_array_entry in sorted_list:
            file = file_array_entry[1]
            message = file_array_entry[2]
            color = file_array_entry[3]
            if Path(file).is_file():
                whole_file = Path(file).read_text()
                if "DO NOT EDIT THIS FILE DIRECTLY" in whole_file:
                    meta_dict = ingest_func.read_metadata(whole_file)

                    # print(file)

                    try:
                        img = re.search(r'<img src="https:\/\/netdata.cloud\/img.*', whole_file)[0].replace(
                            "width=\"150\"", "style={{width: '90%', maxHeight: '100%', verticalAlign: 'middle' }}").replace("<img", "<img custom-image")
                    except TypeError:
                        img = ""

                    md += \
                        f"""
<Box banner="{message}" banner_color="{color}" to="{meta_dict["learn_link"].replace("https://learn.netdata.cloud", "")}"  title="{meta_dict["sidebar_label"]}">
    {img}
</Box>
"""

        md += "\n</Grid>"
        Path(filename.rsplit("/", 1)[0]).mkdir(parents=True, exist_ok=True)
        Path(filename).write_text(md)

        for subdir in sorted(Path(directory).glob("*/")):
            get_dir_make_file_and_recurse(subdir)


for path in Path('docs/data-collection').glob('*/'):
    get_dir_make_file_and_recurse(path)

get_dir_make_file_and_recurse(
    'docs/alerting/notifications/agent-dispatched-notifications')
get_dir_make_file_and_recurse(
    'docs/alerting/notifications/centralized-cloud-notifications')
get_dir_make_file_and_recurse('docs/exporting')
