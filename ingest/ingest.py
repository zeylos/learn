"""
This is the script that gathers markdown files from all of Netdata's repos in this repo
"""
# Imports
import argparse
import glob
import os
import re
import shutil
import errno
import json
import ast
import git
import autogenerateRedirects as genRedirects
import pandas as pd
import numpy as np


"""
Stages of this ingest script:

    Stage_1: Ingest every available markdown from the defaultRepos

    Stage_2: We create three buckets:
                1. markdownFiles: all the markdown files in defaultRepos
                2. reducedMarkdownFiles: all the markdown files that have hidden metadata fields
                3. toPublish: markdown files that must be included in the learn 
                    (metadata_key_value: "learn_status": "Published") 

    Stage_3: 
        1. Move the toPublish markdown files under the DOCS_PREFIX folder based on their metadata (they decide where, 
            they live)
        2. Generate autogenerated pages

    Stage_4: Sanitization
                1. Make the hidden metadata fields actual readable metadata for docusaurus
                2. 
                
    Stage_5: Convert GH links to version specific links
"""


DRY_RUN = False

rest_files_dictionary = {}
rest_files_with_metadata_dictionary = {}
to_publish = {}
markdownFiles = []
BROKEN_LINK_COUNTER = 0
FAIL_ON_NETDATA_BROKEN_LINKS = False
# Temporarily until we release (change it (the default) to /docs
# version_prefix = "nightly"  # We use this as the version prefix in the link strategy
TEMP_FOLDER = "ingest-temp-folder"
default_repos = {
    "netdata":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD": "master",
        },
    "go.d.plugin":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD": "master",
        },
    ".github":
        {
            "owner": "netdata",
            "branch": "main",
            "HEAD": "main",
        },
    "agent-service-discovery":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD": "master",
        },
    "netdata-grafana-datasource-plugin":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD": "master",
        },
    "helmchart":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD": "master",
        }
}


def unsafe_cleanup_folders(folder_to_delete):
    """Cleanup every file in the specified folderToDelete."""
    print("Try to clean up the folder: ", folder_to_delete)
    try:
        shutil.rmtree(folder_to_delete)
        print("Done")
    except Exception as e:
        print("Couldn't delete the folder due to the exception: \n", e)


def produce_gh_view_link_for_repo(repo, file_path):
    """
    This function return the GitHub link (view link) of a repo e.g <owner>/<repo>
    Limitation it produces only  the master, main links only for the netdata org
    """
    if repo == ".github":
        return f"https://github.com/netdata/{repo}/blob/main/{file_path}"
    else:
        return f"https://github.com/netdata/{repo}/blob/master/{file_path}"


def produce_gh_edit_link_for_repo(repo, file_path):
    """
    This function return the GitHub link (view link) of a repo e.g <owner>/<repo>
    Limitation it produces only  the master, main links only for the netdata org
    """
    if repo == ".github":
        return f"https://github.com/netdata/{repo}/edit/main/{file_path}"
    else:
        return "https://github.com/netdata/{repo}/edit/master/{file_path}"


def safe_cleanup_learn_folders(folder_to_delete):
    """
    Cleanup every file in the specified folderToDelete, that doesn't have the `part_of_learn: True`
    metadata in its metadata. It also prints a list of the files that don't have this kind of
    """
    deleted_files = []
    md_files = fetch_markdown_from_repo(folder_to_delete)
    print(f"Files in the {folder_to_delete} folder #{len(md_files)} which are about to be deleted")
    for md in md_files:
        metadata = read_docusaurus_metadata_from_doc(md)
        try:
            if "part_of_learn" in metadata.keys():
                # Reductant condition to emphasize what we are looking for when we clean up learn files
                if metadata["part_of_learn"] == "True":
                    pass
            else:
                deleted_files.append(md)
                os.remove(md)
        except Exception as e:
            print(f"Couldn't delete the {md} file reason: {e}")
    print(f"Cleaned up #{len(deleted_files)} files under {folder_to_delete} folder")


def verify_string_is_dictionary(string_input):
    """
    function to verify that a string input is of dictionary type
    """
    try:
        if isinstance(ast.literal_eval(string_input), dict):
            return True
        else:
            return False
    except:
        return False


def unpack_dictionary_string_to_dictionary(string_input):
    return ast.literal_eval(string_input)


def copy_doc(src, dest):
    """
    Copy a file
    """
    # Get the path
    try:
        shutil.copy(src, dest)
    except IOError as e:
        # ENOENT(2): file does not exist, raised also on missing dest parent dir
        if e.errno != errno.ENOENT:
            raise
        # try creating parent directories
        os.makedirs(os.path.dirname(dest))
        shutil.copy(src, dest)


def clone_repo(owner, repo, branch, depth, prefix_folder):
    """
    Clone a repo in a specific depth and place it under the prefixFolder
    INPUTS:
        https://github.com/{owner}/{repo}:{branch}
        as depth we specify the history of the repo (depth=1 fetches only the latest commit in this repo)
    """
    try:
        output_folder = prefix_folder + repo
        # print("DEBUG", outputFolder)
        git.Git().clone(f"https://github.com/{owner}/{repo}.git", output_folder, depth=depth, branch=branch)
        return f"Cloned the {branch} branch from {repo} repo (owner: {owner})"
    except Exception as e:
        return f"Couldn't clone the {branch} branch from {repo} repo (owner: {owner}) \n Exception {e} raised"


def create_mdx_path_from_metadata(metadata):
    """
    Create a path from the documents metadata
    REQUIRED KEYS in the metadata input:
        [sidebar_label, learn_rel_path]
    In the returned (final) path we sanitize "/", "//" , "-", "," with one dash
    """
    final_file = ' '.join((metadata["sidebar_label"]
                          .replace("'", " ")
                          .replace(":", " ")
                          .replace("/", " ")
                          .replace(")", " ")
                          .replace(",", " ")
                          .replace("(", " ")
                          .replace("`", " ")).split())

    if "Monitor Anything" in metadata['learn_rel_path']\
            and metadata['learn_rel_path'].split("/")[-1] != "Monitor Anything":
        last_folder = metadata['learn_rel_path'].split("Monitor Anything")[1]
        last_folder = "monitor-anything" + last_folder.title()
        # print(lastFolder)
        # If the file is inside the monitor-anything category,
        # meaning that it will try to render the sidebar category label to whatever the folder has,
        # return an array of two things; [the final path, the proper slug].
        # We use the slug to avoid having %20 (replacing spaces) in the link of the file.
        return ["{}/{}/{}.mdx".format(DOCS_PREFIX,
                                      metadata["learn_rel_path"]
                                      .split("Monitor Anything")[0].lower().replace(" ", "-") + last_folder,
                                      final_file.replace(" ", "-")).replace("//", "/"),
                "/{}/{}".format(metadata["learn_rel_path"],
                                final_file.replace(" ", "-")).lower().replace(" ", "-").replace("//", "/")]

    else:
        return ("{}/{}/{}.mdx".format(DOCS_PREFIX,
                                      metadata["learn_rel_path"],
                                      final_file.replace(" ", "-")).lower().replace(" ", "-").replace("//", "/"))


def fetch_markdown_from_repo(output_folder):
    return glob.glob(
        output_folder + '/**/*.md*', recursive=True) + glob.glob(output_folder + '/.**/*.md*', recursive=True)


def insert_and_read_hidden_metadata_from_doc(path_to_file, dictionary):
    """
    Taking a path of a file as input
    Identify the area with pattern " <!-- ...multiline string -->" and  converts them
    to a dictionary of key:value pairs
    """

    repo, path = path_to_file.replace("ingest-temp-folder/", "").split('/', 1)

    if repo == ".github":
        key = "https://github.com/netdata/" + repo + "/edit/main" + "/" + path
    else:
        key = "https://github.com/netdata/" + repo + "/edit/master" + "/" + path

    output = ""
    for field in dictionary.loc[dictionary['custom_edit_url'] == key]:
        try:
            val = dictionary.loc[dictionary['custom_edit_url']
                                 == key][field].values[0]

            # print((not val == np.nan),  val != val, val)
            val = str(val)

            if (not val == np.nan) and val != "nan":
                if field == "sidebar_position":
                    output += "{0}: \"{1}\"\n".format(field, val.replace("\"", ""))
                else:
                    output += "{0}: \"{1}\"\n".format(field, val.replace("\"", ""))
        except:
            pass
            # print("CANT PARSE", mapDict.loc[mapDict['custom_edit_url'] == key][field].values)
    if len(output) > 0:
        output = "<!--\n" + output + "-->\n"
        # print(output)

    dummy_file = open(path_to_file, "r")
    whole_file = dummy_file.read()
    dummy_file.close()

    if whole_file.startswith("<!--"):
        body = whole_file.split("-->", 1)[1]
    else:
        body = whole_file

    dummy_file = open(path_to_file, "w")
    dummy_file.seek(0)
    dummy_file.write(output + body)
    dummy_file.close()

    metadata_dictionary = {}
    with open(path_to_file, "r+") as fd:
        raw_text = "".join(fd.readlines())
        pattern = r"((<!--|---)\n)((.|\n)*?)(\n(-->|---))"
        match_group = re.search(pattern, raw_text)
        if match_group:
            raw_metadata = match_group[3]
            list_metadata = raw_metadata.split("\n")
            while list_metadata:
                line = list_metadata.pop(0)
                split_in_keywords = line.split(": ", 1)
                key = split_in_keywords[0]
                value = split_in_keywords[1]
                if verify_string_is_dictionary(value):
                    value = unpack_dictionary_string_to_dictionary(value)
                # If it's a multiline string
                while list_metadata and len(list_metadata[0].split(": ", 1)) <= 1:
                    line = list_metadata.pop(0)
                    value = value + line.lstrip(' ')
                value = value.strip("\"")
                metadata_dictionary[key] = value.lstrip('>-')
    return metadata_dictionary


def update_metadata_of_file(path_to_file, dictionary):
    """
    Taking a path of a file as input
    Identify the area with pattern " <!-- ...multiline string -->" and  converts them
    to a dictionary of key:value pairs
    """

    output = ""
    for field in dictionary:
        try:
            val = dictionary[field]

            # print((not val == np.nan),  val != val, val)
            val = str(val)
            output += "{0}: \"{1}\"\n".format(field, val.replace("\"", ""))
        except:
            pass
            # print("CANT PARSE", mapDict.loc[mapDict['custom_edit_url'] == key][field].values)
    if len(output) > 0:
        output = "<!--\n" + output + "-->"
        # print(output)

    dummy_file = open(path_to_file, "r")
    whole_file = dummy_file.read()
    dummy_file.close()

    if whole_file.startswith("<!--"):
        body = whole_file.split("-->", 1)[1]
    else:
        body = whole_file

    dummy_file = open(path_to_file, "w")
    dummy_file.seek(0)
    dummy_file.write(output + body)
    dummy_file.close()


def read_docusaurus_metadata_from_doc(path_to_file):
    """
    Taking a path of a file as input
    Identify the area with pattern " <!-- ...multiline string -->" and  converts them
    to a dictionary of key:value pairs
    """
    metadata_dictionary = {}
    with open(path_to_file, "r+") as fd:
        raw_text = "".join(fd.readlines())
        pattern = r"((<!--|---)\n)((.|\n)*?)(\n(-->|---))"
        match_group = re.search(pattern, raw_text)
        if match_group:
            raw_metadata = match_group[3]
            metadata_list = raw_metadata.split("\n")
            while metadata_list:
                line = metadata_list.pop(0)
                split_in_keywords = line.split(": ", 1)
                key = split_in_keywords[0]
                value = split_in_keywords[1]
                if verify_string_is_dictionary(value):
                    value = unpack_dictionary_string_to_dictionary(value)
                # If it's a multiline string
                while metadata_list and len(metadata_list[0].split(": ", 1)) <= 1:
                    line = metadata_list.pop(0)
                    value = value + line.lstrip(' ')
                value = value.strip("\"")
                metadata_dictionary[key] = value.lstrip('>-')
    return metadata_dictionary


def sanitize_page(path):
    """
    Converts the
        "<!--" -> "---"
        "-->" -> "---"
    It converts only the first occurrences of these patterns
    Side effect:
        If the document doesn't have purposeful metadata but it contains this pattern in it's body this function replace
        these patterns
    """

    # Open the file for reading
    file = open(path, "r")
    body = file.read()
    file.close()

    # Replace the metadata with comments
    body = body.replace("<!--", "---", 1)
    body = body.replace("-->", "---", 1)

    # The list with the lines that will be written in the file
    output = []

    # For each line of the file I read
    for line in body.splitlines():
        # If the line isn't an H1 title, and it isn't an analytics pixel, append it to the output list
        if not line.startswith("[![analytics]"):
            output.append(line + "\n")

    # Open the file for overwriting, we are going to write the output list in the file
    file = open(path, "w")
    file.seek(0)
    file.writelines(output)


def reduce_to_publish_in_gh_links_correlation(input_matrix, docs_prefix, docs_path_learn, temp_folder):
    """
    This function takes as an argument our Matrix of the Ingest process and creates a new dictionary with key value
    pairs the Source file (keys) to the Target file (value: learn_absolute path)
    """
    output_dictionary = dict()
    for element in input_matrix:
        repo = input_matrix[element]["ingestedRepo"]
        file_path = element.replace(temp_folder+"/"+repo+"/", "")
        source_link = produce_gh_view_link_for_repo(repo, file_path)
        output_dictionary[source_link] = input_matrix[element]["learnPath"]\
            .split(".mdx")[0]\
            .lstrip('"')\
            .rstrip('"')\
            .replace(docs_prefix, docs_path_learn)
        source_link = produce_gh_edit_link_for_repo(repo, file_path)
        output_dictionary[source_link] = input_matrix[element]["learnPath"]\
            .split(".mdx")[0]\
            .lstrip('"')\
            .rstrip('"')\
            .replace(docs_prefix, docs_path_learn)

        # For now don't remove learnPath, as we need it for the link replacement logic

        # Check for pages that are category overview pages, and have filepath like ".../monitor/monitor".
        # This way we remove the double dirname in the end, because docusaurus routes the file to ../monitor
        if output_dictionary[source_link].split("/")[len(output_dictionary[source_link].split("/"))-1] == \
                output_dictionary[source_link].split("/")[len(output_dictionary[source_link].split("/"))-2]:

            same_parent_dir = output_dictionary[source_link].split(
                "/")[len(output_dictionary[source_link].split("/"))-2]

            proper_link = output_dictionary[source_link].split(same_parent_dir, 1)
            output_dictionary[source_link] = proper_link[0] + \
                proper_link[1].strip("/")

        _temp = output_dictionary[source_link].replace("'", " ").replace(":", " ").replace(")", " ").replace(
            ",", " ").replace("(", " ").replace("/  +/g", ' ').replace(" ", "%20").replace('/-+/', '-')
        # If there is a slug present in the file, then that is the newLearnPath, with a "/docs" added in the front.
        try:
            input_matrix[element].update(
                {"newLearnPath": "/docs"+input_matrix[element]["metadata"]["slug"]})
        except:
            input_matrix[element].update({"newLearnPath": _temp})

    return input_matrix


def convert_github_links(path, arg_dictionary):
    """
    Input:
        path: The path to the markdown file
        fileDic: the fileDictionary with every info about a file

    Expected format of links in files:
        [*](https://github.com/netdata/netdata/blob/master/*)
    """

    # Open the file for reading
    dummy_file = open(path, "r")
    whole_file = dummy_file.read()
    dummy_file.close()

    global BROKEN_LINK_COUNTER

    # Split the file into metadata that this function won't touch and the file's body
    metadata = "---" + whole_file.split("---", 2)[1] + "---"
    body = whole_file.split("---", 2)[2]

    custom_edit_url_arr = re.findall(r'custom_edit_url(.*)', metadata)

    # If there are links inside the body
    if re.search(r"\]\((.*?)\)", body):
        # Find all the links and add them in an array
        urls = []
        temp = re.findall(r'\[\n|.*?]\((\n|.*?)\)', body)
        # For every link, try to not touch the heading that link points to, as it stays the same
        for i in temp:
            try:
                urls.append(i.split('#')[0])
            except:
                urls.append(i)

        for url in urls:

            # The URL will get replaced by the value of the replaceString
            try:
                # The keys inside fileDict are like "ingest-temp-folder/netdata/collectors/charts.d.plugin/ap/README.md"
                # , so from the link, we need:
                # replace the https link prefix until our organization identifier with the prefix of the temp folder
                # try and catch any mishaps in links that instead of "blob" have "edit"
                # remove "blob/master/" or "blob/main/"
                # Then we have the correct key for the dictionary

                dictionary = arg_dictionary[url.replace("https://github.com/netdata", TEMP_FOLDER).replace(
                    "edit", "blob").replace("blob/master/", "").replace("blob/main/", "")]
                replace_string = dictionary["newLearnPath"]

                # In some cases, a "id: someId" will be in a file, this is to change a file's link in Docusaurus,
                # so we need to be careful to honor that
                try:
                    metadata_id = dictionary["metadata"]["id"]

                    replace_string = replace_string.replace(
                        replace_string.split(
                            "/")[len(replace_string.split("/"))-1],
                        metadata_id
                    )
                except:
                    # There is no "id" metadata in the file, do nothing
                    pass

                # In the end replace the URL with the replaceString
                body = body.replace("]("+url, "]("+replace_string)
            except:
                # This is probably a link that can't be translated to a Learn link (e.g. An external file)
                if url.startswith("https://github.com/netdata") and re.search(r"\.md", url):
                    # Increase the counter of the broken links,
                    # fetch the custom_edit_url variable for printing and print a message
                    BROKEN_LINK_COUNTER += 1

                    if len(custom_edit_url_arr[0]) > 1:
                        custom_edit_url = custom_edit_url_arr[0].replace(
                            "\"", "").strip(":")
                    else:
                        custom_edit_url = "NO custom_edit_url found, please add one"

                    print(BROKEN_LINK_COUNTER, "W: In File:", md_file, "\n",
                          "custom_edit_url: ", custom_edit_url, "\n",
                          "URL:", url, "\n")

    # Construct again the whole file
    whole_file = metadata + body

    # Write everything onto the file again
    dummy_file = open(path, "w")
    dummy_file.seek(0)
    dummy_file.write(whole_file)
    dummy_file.close()


def automate_sidebar_position(dictionary):
    # The array that will be returned and placed as a column in the dataFrame
    position = []

    # counters
    counter_one = 0
    counter_two = 0
    counter_three = 0
    counter_four = 0

    # Start from the first entry adn keep it as the previous
    split = dictionary['learn_rel_path'][0].split("/")
    try:
        previous_first_level = split[0]
        previous_second_level = split[1]
        previous_third_level = split[2]
    except:
        pass

    # For every entry, check for every level of the path if it is different,
    # if it is, increment that level's counter by the specified amount.
    for path, i in zip(dictionary['learn_rel_path'], range(0, len(dictionary))):
        if str(path) != "nan":
            split = str(path+f"/{i}").split("/")

            try:
                current_first_level = split[0]
                current_second_level = split[1]
                current_third_level = split[2]
            except:
                pass

            # This works more or less like a Greek abacus
            try:
                if current_first_level != previous_first_level:
                    counter_one += 100000
                    counter_two = 0
                    counter_three = 0
                    counter_four = 0
                elif current_second_level != previous_second_level:
                    counter_two += 2000
                    counter_three = 0
                    counter_four = 0
                elif current_third_level != previous_third_level:
                    counter_three += 40
                    counter_four = 0
                else:
                    counter_four += 1

            except:
                pass

            try:
                previous_first_level = current_first_level
                previous_second_level = current_second_level
                previous_third_level = current_third_level
            except:
                pass

            position.append(counter_one+counter_two+counter_three+counter_four)
        else:
            position.append(-1)

    return position


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Ingest docs from multiple repositories')

    parser.add_argument(
        '--repos',
        default=[],
        nargs='+',
        help='Choose specific repo you want ingest, if not set, defaults ingested'
    )

    parser.add_argument(
        "-d", "--dry-run",
        help="Don't save a file with the output.",
        action="store_true",
    )

    parser.add_argument(
        "--docs-prefix",
        help="Don't save a file with the output.",
        dest="DOCS_PREFIX",
        default="docs"
    )

    parser.add_argument(
        "-f", "--fail-on-internal-broken-links",
        help="Don't proceed with the process if internal broken links are found.",
        action="store_true",
    )

    list_of_repos_in_str = []
    # netdata/netdata:branch tkatsoulas/go.d.plugin:mybranch
    args = parser.parse_args()
    kArgs = args._get_kwargs()
    '''Create local copies from the parse_args input'''
    DOCS_PREFIX = args.DOCS_PREFIX
    for arg in kArgs:
        # print(x)
        if arg[0] == "repos":
            list_of_repos_in_str = arg[1]
        if arg[0] == "dryRun":
            print(arg[1])
            DRY_RUN = arg[1]
        if arg[0] == "fail_on_internal_broken_links":
            FAIL_ON_NETDATA_BROKEN_LINKS = arg[1]

    if len(list_of_repos_in_str) > 0:
        for repo_str in list_of_repos_in_str:
            try:
                _temp = repo_str.split("/")
                repo_owner, repository, repo_branch = [
                    _temp[0]] + (_temp[1].split(":"))
                default_repos[repository]["owner"] = repo_owner
                default_repos[repository]["branch"] = repo_branch
            except (TypeError, ValueError):
                print(
                    "You specified a wrong format in at least one of the repos you want to ingest")
                parser.print_usage()
                exit(-1)
            except KeyError:
                print(repository)
                print("The repo you specified in not in predefined repos")
                print(default_repos.keys())
                parser.print_usage()
                exit(-1)
            except Exception as exc:
                print("Unknown error in parsing", exc)

    '''
    Clean up old clones into a temp dir
    '''
    unsafe_cleanup_folders(TEMP_FOLDER)
    '''
    Clean up old ingested docs
    '''
    safe_cleanup_learn_folders(DOCS_PREFIX)
    print("Creating a temp directory: ", TEMP_FOLDER)
    try:
        os.mkdir(TEMP_FOLDER)
    except FileExistsError:
        print("Folder already exists")

    '''
    Clean up old docs
    '''
    # unSafeCleanUpFolders(DOCS_PREFIX)

    '''Clone all the predefined repos'''
    for repo_name in default_repos.keys():
        print(clone_repo(default_repos[repo_name]["owner"], repo_name,
              default_repos[repo_name]["branch"], 1, TEMP_FOLDER + "/"))
    # This line is useful only during the rework
    # print(cloneRepo("netdata", "learn", "rework-learn", 1, TEMP_FOLDER + "/"))
    # We fetch the markdown files from the repositories
    markdownFiles = fetch_markdown_from_repo(TEMP_FOLDER)
    print("Files detected: ", len(markdownFiles))
    print("Gathering Learn files...")
    # After this we need to keep only the files that have metadata, so we will fetch metadata for everything and keep
    # the entries that have populated dictionaries

    mapDict = pd.read_csv("map.tsv", sep='\t')

    mapDict.set_index('custom_edit_url').T.to_dict('dict')

    mapDict['sidebar_position'] = automate_sidebar_position(mapDict)
    mapDict['sidebar_position'] = mapDict['sidebar_position'].astype(int)

    reduced_markdown_files = []
    for markdown in markdownFiles:
        # print("File: ", md)
        md_metadata = insert_and_read_hidden_metadata_from_doc(markdown, mapDict)
        # Check to see if the dictionary returned is empty
        if len(md_metadata) > 0:
            # print(metadata)
            reduced_markdown_files.append(markdown)
            if "learn_status" in md_metadata.keys():
                if md_metadata["learn_status"] == "Published":
                    try:
                        # check the type of the response (for more info of what the response can be check
                        # the return statements of the function itself)
                        response = create_mdx_path_from_metadata(md_metadata)
                        if type(response) != str:
                            md_metadata.update({"slug": str(response[1])})
                            to_publish[markdown] = {
                                "metadata": md_metadata,
                                "learnPath": str(response[0]),
                                "ingestedRepo": str(markdown.split("/", 2)[1])
                            }
                            update_metadata_of_file(markdown, md_metadata)
                        else:
                            to_publish[markdown] = {
                                "metadata": md_metadata,
                                "learnPath": str(response),
                                "ingestedRepo": str(markdown.split("/", 2)[1])
                            }
                    except Exception as exc:
                        print(
                            f"File {markdown} doesn't contain key-value {KeyError}", exc)

            else:
                rest_files_with_metadata_dictionary[markdown] = {
                    "metadata": md_metadata,
                    "learnPath": str(f"docs/_archive/_{markdown}"),
                    "ingestedRepo": str(markdown.split("/", 2)[1])
                }
        else:
            rest_files_dictionary[markdown] = {"tmpPath": markdown}
        del md_metadata
    # we update the list only with the files that are destined for Learn

    # FILE MOVING
    print("Moving files...")

    # identify published documents:q
    print("Found Learn files: ", len(to_publish))
    # print(json.dumps(toPublish, indent=4))
    # print(json.dumps(toPublish, indent=4))
    for md_file in to_publish:
        copy_doc(md_file, to_publish[md_file]["learnPath"])
        sanitize_page(to_publish[md_file]["learnPath"])
    for md_file in rest_files_with_metadata_dictionary:
        pass
        # moveDoc(file, restFilesDictionary[file]["learnPath"])
    # print("Generating integrations page")
    # genIntPage.generate(toPublish, DOCS_PREFIX+"/getting-started/integrations.mdx")
    # print("Done")

    print("Fixing github links...")
    # After the moving, we have a new metadata, called newLearnPath, and we utilize that to fix links that were
    # pointing to GitHub relative paths
    # print(json.dumps(reduceToPublishInGHLinksCorrelation(toPublish, DOCS_PREFIX, "/docs", TEMP_FOLDER), indent=4))
    file_dict = reduce_to_publish_in_gh_links_correlation(
        to_publish, DOCS_PREFIX, "/docs", TEMP_FOLDER)
    # print(json.dumps(fileDict, indent=4))
    for md_file in to_publish:
        convert_github_links(file_dict[md_file]["learnPath"], file_dict)
    genRedirects.main(file_dict)
    print("Done.", "Broken Links:", BROKEN_LINK_COUNTER)
    print(FAIL_ON_NETDATA_BROKEN_LINKS, BROKEN_LINK_COUNTER)
    if FAIL_ON_NETDATA_BROKEN_LINKS and BROKEN_LINK_COUNTER > 0:
        print("\nFOUND BROKEN LINKS, ABORTING...")
        exit(-1)

    if len(rest_files_with_metadata_dictionary) > 0:
        print("These files are in repos and dont have valid metadata to publish them in learn")
    for md_file in rest_files_with_metadata_dictionary:
        if "custom_edit_url" in rest_files_with_metadata_dictionary[md_file]["metadata"]:
            print(rest_files_with_metadata_dictionary[md_file]["metadata"]["custom_edit_url"], md_file)
        else:
            print("Custom edit url not found, printing any metadata and its position when we ingest it")
            print(json.dumps(rest_files_with_metadata_dictionary[md_file]["metadata"], indent=4))
            print("&Position: ", md_file)
    if len(rest_files_dictionary):
        print("ABORT: Files found that are not in the map, exiting...")
        for md_file in rest_files_dictionary:
            print(rest_files_dictionary[md_file]["tmpPath"])
        exit(-1)

    # Write the current dict into a file, so we can check for redirects in the next commit
    temp_dict = {}
    custom_edit_urls_array = []
    new_learn_paths_array = []

    for repo_name in file_dict:
        custom_edit_urls_array.append(file_dict[repo_name]["metadata"]["custom_edit_url"])
        new_learn_paths_array.append(file_dict[repo_name]["newLearnPath"])

    temp_dict['custom_edit_url'] = custom_edit_urls_array
    temp_dict['learn_path'] = new_learn_paths_array

    df = pd.DataFrame.from_dict(temp_dict)
    df.set_index('custom_edit_url')
    df.to_csv("./ingest/one_commit_back_file-dict.tsv", sep='\t', index=False)

    unsafe_cleanup_folders(TEMP_FOLDER)

print("OPERATION FINISHED")
