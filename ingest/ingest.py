# Imports
import argparse
import copy
import glob
import itertools
import os
import pathlib
import re
import shutil
import errno
import git
import json
import ast
import autogenerateSupportedIntegrationsPage as genIntPage


"""
Stages of this ignest sript:

    Stage_1: Ingest every available markdown from the defaultRepos
    
    Stage_2: We create three buckets:
                1. markdownFiles: all the markdown files in defaultRepos
                2. reducedMarkdownFiles: all the markdown files that have hidden metadata fields
                3. toPublish: markdown files that must be included in the learn (metadata_key_value: "learn_status": "Published") 

    Stage_3: 
        1. Move the toPublish markdown files under the DOCS_PREFIX folder based on their metadata (they decide where, 
            they live)
        2. Generate autogenerated pages         
            
    Stage_4: Sanitization
                1. Make the hidden metadata fields actual readable metadata for docusaurus
                2. 
                
    Stage_5: Convert GH links to version specific links
"""



dryRun = False

restFilesDictionary = {}
restFilesWithMetadataDictionary = {}
toPublish = {}
markdownFiles = []
BROKEN_LINK_COUNTER= 0
FAIL_ON_NETDATA_BROKEN_LINKS = False 
 #Temporarily until we release (change it (the default) to /docs
version_prefix = "nightly"  # We use this as the version prefix in the link strategy
TEMP_FOLDER = "ingest-temp-folder"
defaultRepos = {
    "netdata":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD" : "master",
        },
    "go.d.plugin":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD" : "master",
        },
    ".github":
        {
            "owner": "netdata",
            "branch": "main",
            "HEAD" : "main",
        },
    "agent-service-discovery":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD" : "master",
        },
    "netdata-grafana-datasource-plugin":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD" : "master",
        },
    "helmchart":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD" : "master",
        },
    "agent-service-discovery":
        {
            "owner": "netdata",
            "branch": "master",
            "HEAD" : "master",
        },
}


# defaultRepoInaStr = " ".join(defaultRepo)
# print(defaultRepoInaStr)

# Will come back to this once we have a concrete picture of the script
# if sys.argv[1] == "dry-run":
#     print("--- DRY RUN ---\n")
#     dry_run = True

def unSafeCleanUpFolders(folderToDelete):
    """Cleanup every file in the specified folderToDelete."""
    print("Try to clean up the folder: ", folderToDelete)
    try:
        shutil.rmtree(folderToDelete)
        print("Done")
    except Exception as e:
        print("Couldn't delete the folder due to the exception: \n", e)


def produceGHViewLinkForRepo(repo, filePath):
    """
    This function return the GitHub link (view link) of a repo e.g <owner>/<repo>
    Limitation it produces only  the master, main links only for the netdata org
    """
    if repo == ".github":
        return("https://github.com/netdata/{}/blob/main/{}".format(repo, filePath))
    else:
        return("https://github.com/netdata/{}/blob/master/{}".format(repo, filePath))

def produceGHEditLinkForRepo(repo, filePath):
    """
    This function return the GitHub link (view link) of a repo e.g <owner>/<repo>
    Limitation it produces only  the master, main links only for the netdata org
    """
    if repo == ".github":
        return("https://github.com/netdata/{}/edit/main/{}".format(repo, filePath))
    else:
        return("https://github.com/netdata/{}/edit/master/{}".format(repo, filePath))


def safeCleanUpLearnFolders(folderToDelete):
    """
    Cleanup every file in the specified folderToDelete, that doesn't have the `part_of_learn: True`
    metadata in its metadata. It also prints a list of the files that don't have this kind of
    """
    deletedFiles = []
    markdownFiles = fetchMarkdownFromRepo(folderToDelete)
    print("Files in the {} folder #{} which are about to be deleted".format(folderToDelete, len(markdownFiles)))
    unmanagedFiles = []
    for md in markdownFiles:
        metadata = readDocusaurusMetadataFromDoc(md)
        try:
            if "part_of_learn" in metadata.keys():
                # Reductant condition to emphasize what we are looking for when we clean up learn files
                if metadata["part_of_learn"] == "True":
                    pass
            else:
                deletedFiles.append(md)
                os.remove(md)
        except Exception as e:
            print("Couldnt delete the {} file reason: {}".format(md, e))
    print("Cleaned up #{} files under {} folder".format(len(deletedFiles), folderToDelete))

def verifyStringIsDictionary(stringInput):
    try:
        if type(ast.literal_eval(stringInput)) is dict:
            return(True)
        else:
            return(False)
    except:
        return(False)

def unpackDictionaryStringToDictionary(stringInput):
    return(ast.literal_eval(stringInput))

def renameReadmes(fileArray):
    """
    DEPRECATED: to be deleted in v1.0 of this ingest
    In this function we will get the whole list of files,
    search for README named files, and rename them in accordance to their parent dir name.
    After we rename, we need to update the list entry.
    """
    # TODO think of a way of not renaming the unpublished files (?) this will affect only the README s
    counter = 0
    for filename in fileArray:
        if filename.__contains__("README"):
            # Get the path without the filename
            filename = pathlib.Path(filename)
            # And then from that take the last dir, which is the name we want to rename to, add a needed "/" and the
            # ".md"
            newPath = os.path.dirname(filename) + "/" + os.path.basename(filename.parent.__str__()[1:]) + ".md"

            os.rename(filename, newPath)
            fileArray[counter] = newPath
        counter += 1


def copyDoc(src, dest):
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


def cloneRepo(owner, repo, branch, depth, prefixFolder):
    """
    Clone a repo in a specific depth and place it under the prefixFolder
    INPUTS:
        https://github.com/{owner}/{repo}:{branch}
        as depth we specify the history of the repo (depth=1 fetches only the latest commit in this repo)
    """
    try:
        outputFolder = prefixFolder + repo
        # print("DEBUG", outputFolder)
        git.Git().clone("https://github.com/{}/{}.git".format(owner, repo), outputFolder, depth=depth, branch=branch)
        return "Cloned the {} branch from {} repo (owner: {})".format(branch, repo, owner)
    except Exception as e:
        return (
            "Couldn't clone the {} branch from {} repo (owner: {}) \n Exception {} raised".format(branch, repo, owner,
                                                                                                  e))


def createMDXPathFromMetdata(metadata):
    """
    Create a path from the documents metadata
    REQUIRED KEYS in the metadata input:
        [sidebar_label, learn_rel_path]
    In the returned (final) path we sanitize "/", "//" , "-", "," with one dash
    """
    finalFile = ' '.join(
        (metadata["sidebar_label"].replace("'", " ").replace("/", " ").replace(")", " ").replace(",", " ").replace("(", " ")).split())
    return ("{}/{}/{}.mdx".format(DOCS_PREFIX, \
                                  metadata["learn_rel_path"], \
                                  finalFile.replace(" ", "-")).lower().replace(" ", "-").replace("//", "/"))


def fetchMarkdownFromRepo(outputFolder):
    return (glob.glob(outputFolder + '/**/*.md*', recursive=True) + glob.glob(outputFolder + '/.**/*.md*', recursive=True))


def readHiddenMetadataFromDoc(pathToFile):
    """
    Taking a path of a file as input
    Identify the area with pattern " <!-- ...multiline string -->" and  converts them
    to a dictionary of key:value pairs
    """
    metadataDictionary = {}
    with open(pathToFile, "r+") as fd:
        rawText = "".join(fd.readlines())
        pattern = r"((<!--|---)\n)((.|\n)*?)(\n(-->|---))"
        matchGroup = re.search(pattern, rawText)
        if matchGroup:
            rawMetadata = matchGroup[3]
            listMetadata = rawMetadata.split("\n")
            while listMetadata:
                line = listMetadata.pop(0)
                splitInKeywords = line.split(": ",1)
                key = splitInKeywords[0]
                value = splitInKeywords[1]
                if verifyStringIsDictionary(value):
                    value = unpackDictionaryStringToDictionary(value)
                # If it's a multiline string
                while listMetadata and len(listMetadata[0].split(": ",1)) <= 1:
                    line = listMetadata.pop(0)
                    value = value + line.lstrip(' ')
                value = value.strip("\"")
                metadataDictionary[key] = value.lstrip('>-')
    return metadataDictionary

def readDocusaurusMetadataFromDoc(pathToFile):
    """
    Taking a path of a file as input
    Identify the area with pattern " <!-- ...multiline string -->" and  converts them
    to a dictionary of key:value pairs
    """
    metadataDictionary = {}
    with open(pathToFile, "r+") as fd:
        rawText = "".join(fd.readlines())
        pattern = r"((<!--|---)\n)((.|\n)*?)(\n(-->|---))"
        matchGroup = re.search(pattern, rawText)
        if matchGroup:
            rawMetadata = matchGroup[3]
            listMetadata = rawMetadata.split("\n")
            while listMetadata:
                line = listMetadata.pop(0)
                splitInKeywords = line.split(": ",1)
                key = splitInKeywords[0]
                value = splitInKeywords[1]
                if verifyStringIsDictionary(value):
                    value = unpackDictionaryStringToDictionary(value)
                # If it's a multiline string
                while listMetadata and len(listMetadata[0].split(": ",1)) <= 1:
                    line = listMetadata.pop(0)
                    value = value + line.lstrip(' ')
                value = value.strip("\"")
                metadataDictionary[key] = value.lstrip('>-')
    return metadataDictionary


def sanitizePage(path):
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
        if not line.startswith("# ") and not line.startswith("[![analytics]"):
            output.append(line + "\n")

    # TODO remove github badges

    # Open the file for overwriting, we are going to write the output list in the file
    file = open(path, "w")
    file.seek(0)
    file.writelines(output)


def reductToPublishInGHLinksCorrelation(inputMatrix, DOCS_PREFIX, DOCS_PATH_LEARN, TEMP_FOLDER):
    """
    This function takes as an argument our Matrix of the Ingest process and creates a new dictionary with key value
    pairs the Source file (keys) to the Target file (value: learn_absolute path)
    """
    outputDictionary = dict()
    for x in inputMatrix:
        repo = inputMatrix[x]["ingestedRepo"]
        filePath = x.replace(TEMP_FOLDER+"/"+repo+"/", "")
        sourceLink = produceGHViewLinkForRepo(repo, filePath)
        outputDictionary[sourceLink] = inputMatrix[x]["learnPath"].split(".mdx")[0].lstrip('"').rstrip('"').replace(
            DOCS_PREFIX, DOCS_PATH_LEARN)
        sourceLink = produceGHEditLinkForRepo(repo, filePath)
        outputDictionary[sourceLink] = inputMatrix[x]["learnPath"].split(".mdx")[0].lstrip('"').rstrip('"').replace(
            DOCS_PREFIX, DOCS_PATH_LEARN)
        
        # For now don't remove learnPath, as we need it for the link replacement logic
        inputMatrix[x].update({"newLearnPath": outputDictionary[sourceLink]})

    return (inputMatrix)


def convertGithubLinks(path, fileDict, DOCS_PREFIX):
    '''
    Input:
        path: The path to the markdown file
        fileDic: the fileDictionary with every info about a file

    Expected format of links in files:
        [*](https://github.com/netdata/netdata/blob/master/*)
    '''

    # Open the file for reading
    dummyFile = open(path, "r")
    wholeFile = dummyFile.read()
    dummyFile.close()

    global BROKEN_LINK_COUNTER

    custom_edit_url = ""

    # Split the file into metadata that this function won't touch and the file's body
    metadata = "---" + wholeFile.split("---", 2)[1] + "---"
    body = wholeFile.split("---", 2)[2]

    custom_edit_url_arr = re.findall(r'custom_edit_url(.*)', metadata)

    # If there are links inside the body
    if re.search("\]\((.*?)\)", body):
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
                # The keys inside fileDict are like "ingest-temp-folder/netdata/collectors/charts.d.plugin/ap/README.md", so from the link, we need:
                # replace the https link prefix until our organization identifier with the prefix of the temp folder
                # try and catch any mishaps in links that instead of "blob" have "edit"
                # remove "blob/master/" or "blob/main/"
                # Then we have the correct key for the dictionary

                dict = fileDict[url.replace("https://github.com/netdata", TEMP_FOLDER).replace(
                    "edit", "blob").replace("blob/master/", "").replace("blob/main/", "")]
                replaceString = dict["newLearnPath"]

                # In some cases, a "id: someId" will be in a file, this is to change a file's link in Docusaurus, so we need to be careful to honor that
                try:
                    id = dict["metadata"]["id"]

                    replaceString = replaceString.replace(
                        replaceString.split(
                            "/")[len(replaceString.split("/"))-1],
                        id
                    )
                except:
                    # There is no "id" metadata in the file, do nothing
                    pass

                # Check for pages that are category overview pages, and have filepath like ".../monitor/monitor".
                # This way we remove the double dirname in the end, because docusaurus routes the file to ../monitor
                if replaceString.split("/")[len(replaceString.split("/"))-1] == replaceString.split("/")[len(replaceString.split("/"))-2]:
                    sameParentDir = replaceString.split(
                        "/")[len(replaceString.split("/"))-2]

                    properLink = replaceString.split(sameParentDir, 1)
                    replaceString = properLink[0] + properLink[1].strip("/")

                # In the end replace the URL with the replaceString
                body = body.replace("]("+url, "]("+replaceString)
            except:
                # This is probably a link that can't be translated to a Learn link (e.g. An external file)
                if url.startswith("https://github.com/netdata") and re.search("\.md", url):
                    # Increase the counter of the broken links, fetch the custom_edit_url variable for printing and print a message
                    BROKEN_LINK_COUNTER += 1

                    if len(custom_edit_url_arr[0]) > 1:
                        custom_edit_url = custom_edit_url_arr[0].replace(
                            "\"", "").strip(":")
                    else:
                        custom_edit_url = "NO custom_edit_url found, please add one"

                    print(BROKEN_LINK_COUNTER, "W: In File:", file, "\n",
                          "custom_edit_url: ", custom_edit_url, "\n",
                          "URL:", url, "\n")

    # Construct again the whole file
    wholeFile = metadata + body

    # Write everything onto the file again
    dummyFile = open(path, "w")
    dummyFile.seek(0)
    dummyFile.write(wholeFile)
    dummyFile.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Ingest docs from multiple repositories')

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
        default="versioned_docs/version-nightly"
    )
    
    parser.add_argument(
        "-f", "--fail-on-internal-broken-links",
        help="Don't proceed with the process if internal broken links are found.",
        action="store_true",
    )


    listOfReposInStr = []
    # netdata/netdata:branch tkatsoulas/go.d.plugin:mybranch
    args = parser.parse_args()
    kArgs = args._get_kwargs()
    '''Create local copies from the argpase input'''
    DOCS_PREFIX = args.DOCS_PREFIX
    for x in kArgs:
        print(x)
        if x[0] == "repos":
            listOfReposInStr = x[1]
        if x[0] == "dryRun":
            print(x[1])
            dryRun = x[1]
        if x[0] == "fail_on_internal_broken_links":
            FAIL_ON_NETDATA_BROKEN_LINKS = x[1]

    if len(listOfReposInStr) > 0:
        for repoStr in listOfReposInStr:
            try:
                _temp = repoStr.split("/")
                owner, repo, branch = [_temp[0]] + (_temp[1].split(":"))
                defaultRepos[repo]["owner"] = owner
                defaultRepos[repo]["branch"] = branch
            except(TypeError, ValueError):
                print("You specified a wrong format in at least one of the repos you want to ingest")
                parser.print_usage()
                exit(-1)
            except KeyError:
                print(repo)
                print("The repo you specified in not in predefined repos")
                print(defaultRepos.keys())
                parser.print_usage()
                exit(-1)
            except Exception as e:
                print("Unknown error in parsing", e)

    '''
    Clean up old clones into a temp dir
    '''
    unSafeCleanUpFolders(TEMP_FOLDER)
    '''
    Clean up old ingested docs
    '''
    safeCleanUpLearnFolders(DOCS_PREFIX)
    print("Creating a temp directory: ",TEMP_FOLDER)
    try:
        os.mkdir(TEMP_FOLDER)
    except FileExistsError:
        print("Folder already exists")

    '''
    Clean up old docs
    '''
    #unSafeCleanUpFolders(DOCS_PREFIX)

    '''Clone all the predefined repos'''
    for key in defaultRepos.keys():
        print(cloneRepo(defaultRepos[key]["owner"], key, defaultRepos[key]["branch"], 1, TEMP_FOLDER + "/"))
    # This line is useful only during the rework
    #print(cloneRepo("netdata", "learn", "rework-learn", 1, TEMP_FOLDER + "/"))
    # We fetch the markdown files from the repositories
    markdownFiles = fetchMarkdownFromRepo(TEMP_FOLDER)
    print("Files detected: ", len(markdownFiles))
    print("Gathering Learn files...")
    # After this we need to keep only the files that have metadata, so we will fetch metadata for everything and keep
    # the entries that have populated dictionaries
    reducedMarkdownFiles = []
    for md in markdownFiles:
        #print("File: ", md)
        metadata = readHiddenMetadataFromDoc(md)
        # Check to see if the dictionary returned is empty
        if len(metadata) > 0:
            #print(metadata)
            reducedMarkdownFiles.append(md)
            if "learn_status" in metadata.keys():
                if metadata["learn_status"] == "Published":
                    try:
                        toPublish[md] = {
                            "metadata": metadata,
                            "learnPath": str(createMDXPathFromMetdata(metadata)),
                            "ingestedRepo": str(md.split("/", 2)[1])
                        }
                    except:
                        print("File {} doesnt container key-value {}".format(md, KeyError))
            else:
                restFilesWithMetadataDictionary[md] = {
                    "metadata": metadata,
                    "learnPath": str("docs/_archive/_{}".format(md)),
                    "ingestedRepo": str(md.split("/", 2)[1])
                }
        else:
            restFilesDictionary[md] = {"tmpPath": md}
        del metadata
    # we update the list only with the files that are destined for Learn

    # FILE MOVING
    print("Moving files...")

    # identify published documents:q
    print("Found Learn files: ", len(toPublish))
    #print(json.dumps(toPublish, indent=4))
    #print(json.dumps(toPublish, indent=4))
    for file in toPublish:
        copyDoc(file, toPublish[file]["learnPath"])
        sanitizePage(toPublish[file]["learnPath"])
    for file in restFilesWithMetadataDictionary:
        pass
        # moveDoc(file, restFilesDictionary[file]["learnPath"])
    #print("Generating integrations page")
    #genIntPage.generate(toPublish, DOCS_PREFIX+"/getting-started/integrations.mdx")
    #print("Done")

    print("Fixing github links...")
    # After the moving, we have a new metadata, called newLearnPath, and we utilize that to fix links that were
    # pointing to GitHub relative paths
    #print(json.dumps(reductToPublishInGHLinksCorrelation(toPublish, DOCS_PREFIX, "/docs/"+version_prefix, TEMP_FOLDER), indent=4))
    for file in toPublish:
        fileDict = reductToPublishInGHLinksCorrelation(toPublish, DOCS_PREFIX, "/docs/"+version_prefix, TEMP_FOLDER)
        convertGithubLinks(fileDict[file]["learnPath"],fileDict , DOCS_PREFIX)
    print("Done.", "Broken Links:", BROKEN_LINK_COUNTER)
    print(FAIL_ON_NETDATA_BROKEN_LINKS, BROKEN_LINK_COUNTER)
    if FAIL_ON_NETDATA_BROKEN_LINKS and BROKEN_LINK_COUNTER>0:
        print("\nFOUND BROKEN LINKS, ABORTING...")
        exit(-1)

    if len(restFilesWithMetadataDictionary)>0:
        print("These files are in repos and dont have valid metadata to publish them in learn")
    for file in restFilesWithMetadataDictionary:
        if "custom_edit_url" in restFilesWithMetadataDictionary[file]["metadata"]:
            print(restFilesWithMetadataDictionary[file]["metadata"]["custom_edit_url"], file)
        else:
            print("Custom edit url not found, printing any metadata and its position when we ingest it" )
            print(json.dumps(restFilesWithMetadataDictionary[file]["metadata"], indent=4))
            print("&Position: ", file)
    if len(restFilesDictionary):
        print("These markdown files are in our repos and dont have any metadata at all")
    for file in restFilesDictionary:
        print(restFilesDictionary[file]["tmpPath"])

    unSafeCleanUpFolders(TEMP_FOLDER)

print("OPERATION FINISHED")
