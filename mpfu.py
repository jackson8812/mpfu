#!/usr/bin/env python3

import os, sys, platform, socket, getpass, glob, ftplib, paramiko, scp, warnings, urllib, boto3
from smb.SMBHandler import SMBHandler
from botocore.exceptions import NoCredentialsError, ClientError
from halo import Halo

# Detect platform
plat_type = platform.system()

# Platform specific imports
if plat_type == 'Linux':
    import readline
if plat_type == 'Windows':
    import colorama
    colorama.init()
    import pyreadline
    import readline

# Color tags
if plat_type == 'Linux':
    b_ = '\033[94m'
if plat_type == 'Windows':
    b_ = '\033[95m'
g_ = '\033[92m'
r_ = '\033[91m'
y_ = '\033[1;33m'
p_ = '\033[1;35m'
bld_ = '\033[1m'
_nc = '\033[0m'

# Filter paramiko warnings until new version with bugfix released
warnings.filterwarnings(action='ignore',module='.*paramiko.*')

# Tab completion code from https://gist.github.com/iamatypeofwalrus/5637895
class tabCompleter(object):

    def pathCompleter(self, text, state):
        line = readline.get_line_buffer().split()

        # replace ~ with the user's home dir. See https://docs.python.org/2/library/os.path.html
        if '~' in text:
            text = os.path.expanduser('~')

        # autocomplete directories with having a trailing slash
        if os.path.isdir(text):
            text += '/'

        return [x for x in glob.glob(text + '*')][state]


    def createListCompleter(self,ll):
        def listCompleter(text,state):
            line   = readline.get_line_buffer()

            if not line:
                return [c + " " for c in ll][state]

            else:
                return [c + " " for c in ll if c.startswith(line)][state]

        self.listCompleter = listCompleter

# Function that enables above tab completer
def bashCompleter():
    global t
    t = tabCompleter()
    t.createListCompleter(["ab","aa","bcd","bdf"])

    readline.set_completer_delims('\t')
    readline.parse_and_bind("tab: complete")

    readline.set_completer(t.pathCompleter)

# Transfer progress provider from https://github.com/jonDel/ssh_paramiko
def pbar(transfered_bytes, total_bytes):
    bar_length = 35
    percent = float(transfered_bytes) / total_bytes
    hashes = '#' * int(round(percent * bar_length))
    spaces = ' ' * (bar_length - len(hashes))
    message = "\rSize: "+str(total_bytes)+" bytes("\
              +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
    message += " || Amount of file transferred: [{0}] {1}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
    if transfered_bytes == total_bytes:
        message = "\rSize: "+str(total_bytes)+" bytes("\
                  +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
        message += " || File transferred. [{0}] {1}%                    \r"\
                   .format(hashes + spaces, round(percent * 100, 2))
    sys.stdout.write(message)
    sys.stdout.flush()

# Modified progress provider for ftplib. fbar_bytes set to 0 initially to make func work
fbar_bytes = 0

def fbar(ftp_bytes):
    global fbar_bytes
    total_bytes = bar_f_size
    fbar_bytes += 8192
    bar_length = 35
    percent = float(fbar_bytes) / total_bytes
    hashes = '#' * int(round(percent * bar_length))
    spaces = ' ' * (bar_length - len(hashes))
    message = "\rSize: "+str(total_bytes)+" bytes("\
              +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
    message += " || Amount of file transferred: [{0}] {1}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
    if fbar_bytes >= total_bytes:
        message = "\rSize: "+str(total_bytes)+" bytes("\
                  +str(round(float(total_bytes)/pow(2, 20),2))+" MB)"
        message += " || File transferred. [{0}] {1}%                    \r"\
                   .format(hashes + spaces, round(percent * 100))
        fbar_bytes = 0
    sys.stdout.write(message)
    sys.stdout.flush()

# Modified progress provider for SCP. fname parameter added but left blank to align with scp module callback output
def sbar(fname, total_bytes, transfered_bytes):
    bar_length = 35
    percent = float(transfered_bytes) / total_bytes
    hashes = '#' * int(round(percent * bar_length))
    spaces = ' ' * (bar_length - len(hashes))
    message = "\rSize: "+str(total_bytes)+" bytes("\
              +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
    message += " || Amount of file transferred: [{}] {}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
    if transfered_bytes == total_bytes:
        message = "\rSize: "+str(total_bytes)+" bytes("\
                  +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
        message += " || File transferred. [{}] {}%                    \r"\
                   .format(hashes + spaces, round(percent * 100, 2))
    sys.stdout.write(message)
    sys.stdout.flush()

# Modified progress provider for S3. boto3 only sends transferred bytes each update.
def s3bar(t_bytes):
    global s3_bytes
    s3_bytes += t_bytes
    bar_length = 35
    percent = float(s3_bytes) / s3_f_size
    hashes = '#' * int(round(percent * bar_length))
    spaces = ' ' * (bar_length - len(hashes))
    message = "\rSize: "+str(s3_f_size)+" bytes("\
              +str(round(float(s3_f_size)/pow(2, 20), 2))+" MB)"
    message += " || Amount of file transferred: [{}] {}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
    if s3_bytes == s3_f_size:
        message = "\rSize: "+str(s3_f_size)+" bytes("\
                  +str(round(float(s3_f_size)/pow(2, 20), 2))+" MB)"
        message += " || File transferred. [{}] {}%                    \r"\
                   .format(hashes + spaces, round(percent * 100, 2))
    sys.stdout.write(message)
    sys.stdout.flush()

# Protocol prompt function
def protPrompt():
    global protvar
    # Get connection and file path details
    print("""
Choose destination type:

1) FTP
2) SFTP
3) SCP
4) CIFS/SMB (Windows File Share)
5) AWS S3""")

    protvar = input("\nEnter protocol [1-5]: ")

    if protvar == "1":
        protvar = "ftp"
    elif protvar == "2":
        protvar = "sftp"
    elif protvar == "3":
        protvar = "scp"
    elif protvar == "4":
        protvar = "smb"
    elif protvar == "5":
        protvar = "s3"

    # Warn about FTP security, SMB risk
    if protvar == "ftp":
        print("\nNote: {}FTP{} protocol is inherently {}insecure{}, your password will be encrypted, but file(s) are sent unencrypted!\n".format(y_,_nc,r_,_nc))
    elif protvar == "smb":
        print("\n{}!!!WARNING!!!{} This utility will overwrite any file on the share with same name as the uploaded file. {}USE CAUTION!{}".format(r_,_nc,y_,_nc))

# Credentials prompt function
def credPrompt():
    global uservar
    uservar = input("\nUsername: ")

    global passvar
    passvar = getpass.getpass("\nPassword: ")

# Prompt for local dir and file(s) function
def localfsPrompt():
    global dirvar
    global filevar
    readline.set_completer(t.pathCompleter)
    dirvar = input("\nLocal directory containing files to upload (include leading slash): ")
    print("\nContents of directory: \n")

    # On Windows, tab completer allows path all the way to filename. This block handles that case.
    if os.path.isfile(dirvar):
        filevar = os.path.basename(dirvar)
        dirvar = os.path.dirname(dirvar)
        return

    # Filter subdirectories out of directory contents
    dirvarlist = os.listdir(dirvar)
    for file in dirvarlist:
        dirvaritem = os.path.join(dirvar, file)
        if os.path.isdir(dirvaritem):
            dirvarlist.remove(file)
    dirlist = '\n'.join(map(str,dirvarlist))
    print(dirlist)

    # Feed directory contents list into tab completer
    t.createListCompleter(dirvarlist)
    readline.set_completer(t.listCompleter)
    filevar = input("\nFile(s) to upload (wildcards accepted): ")
    print("")

# Try load in last server connection from sav.mpfu, if doesn't exist create it
try:
    lastserv_f = open('sav.mpfu').readlines()
    lastserv = lastserv_f[-1].strip()
except IOError:
    lastserv_f = open('sav.mpfu', 'w')
    lastserv_f.close()
    lastserv = ""
except IndexError:
    lastserv = ""

# Actual multi-protocol uploader function
def finalUpload(protvar,servvar,uservar,passvar,dirvar,filevar,remdirvar):

    # Pull path list into a glob for parsing
    fileglob = glob.glob(os.path.join(dirvar, filevar.strip()))

    if protvar == "ftp":
        try:
            session = ftplib.FTP_TLS()
            session.connect(servvar, 21)
            session.sendcmd('USER {}'.format(uservar))
            session.sendcmd('PASS {}'.format(passvar))
            if remdirvar != "":
                session.sendcmd('cwd {}'.format(remdirvar))
            resp_pwd = session.sendcmd('pwd')
            ftp_pwd = resp_pwd.lstrip('0123456789" ').rstrip('"')
            if plat_type == 'Linux':
                os.system('setterm -cursor off')
            for g in fileglob:
                if os.path.isdir(g):
                    continue
                gfile = str(os.path.basename(g))
                file = open('{}'.format(g), 'rb')
                global bar_f_size
                global transfered_bytes
                transfered_bytes = 0
                bar_f_size = os.path.getsize(g)
                if remdirvar == "":
                    remdirvar = "[default]"
                print("Sending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,servvar,_nc,p_,ftp_pwd,_nc,y_,protvar.upper(),_nc))
                session.storbinary('STOR ' + gfile, file,callback=fbar)
                print("\n\n")
                file.close()
            session.quit()
            if plat_type == 'Linux':
                os.system('setterm -cursor on')
        except ftplib.all_errors as e:
            print("""
{}<ERROR>
The server raised an exception: {} {}\n""".format(r_,e,_nc))
            input("Press a key to continue...")
            print(" ")
            return
    if protvar == "sftp":
        try:
            pssh = paramiko.SSHClient()
            pssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            pssh.connect(hostname=servvar,username=uservar,password=passvar,timeout=8)
            sftpc = pssh.open_sftp()
            if plat_type == 'Linux':
                os.system('setterm -cursor off')
            for g in fileglob:
                if os.path.isdir(g):
                    continue
                gfile = str(os.path.basename(g))
                print("Sending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,servvar,_nc,p_,remdirvar,_nc,y_,protvar.upper(),_nc))
                sftpc.put(g,remdirvar + gfile,callback=pbar)
                print("\n\n")
            sftpc.close()
            if plat_type == 'Linux':
                os.system('setterm -cursor on')
        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.BadAuthenticationType):
            print("""
{}<ERROR>
Username, password, or SSH key are incorrect, or the server is not accepting the type of authentication attempted{}.\n""".format(r_,_nc))
            input("Press a key to continue...")
            print(" ")
            return
        except (BlockingIOError, socket.timeout):
            print("""
{}<ERROR>
Server is offline, unavailable, or otherwise not responding. Check the hostname or IP and try again.{}\n""".format(r_,_nc))
            input("Press a key to continue...")
            print(" ")
            return
        except socket.gaierror as e:
            print("""
{}<ERROR>
The server raised an exception: {} {}\n""".format(r_,e,_nc))
            input("Press a key to continue...")
            print(" ")
            return
        except WindowsError as e:
            print("""
{}<ERROR>
The server raised an exception: {} {}\n""".format(r_,e,_nc))
            input("Press a key to continue...")
            print(" ")
            return

    if protvar == "scp":
        try:
            pssh = paramiko.SSHClient()
            pssh.load_system_host_keys()
            pssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            pssh.connect(hostname=servvar,username=uservar,password=passvar, timeout=8)
            pscp = scp.SCPClient(pssh.get_transport(), progress=sbar)
            if plat_type == 'Linux':
                os.system('setterm -cursor off')
            for g in fileglob:
                if os.path.isdir(g):
                    continue
                gfile = str(os.path.basename(g))
                print("Sending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,servvar,_nc,p_,remdirvar,_nc,y_,protvar.upper(),_nc))
                pscp.put(g, remote_path=remdirvar)
                print("\n\n")
            pscp.close()
            if plat_type == 'Linux':
                os.system('setterm -cursor on')
        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.BadAuthenticationType):
            print("""
{}<ERROR>
Username, password, or SSH key are incorrect, or the server is not accepting the type of authentication attempted{}.\n""".format(r_,_nc))
            input("Press a key to continue...")
            print(" ")
            return
        except (BlockingIOError, socket.timeout):
            print("""
{}<ERROR>
Server is offline, unavailable, or otherwise not responding. Check the hostname or IP and try again.{}\n""".format(r_,_nc))
            input("Press a key to continue...")
            print(" ")
            return
        except scp.SCPException as e:
            print("""
{}<ERROR>
The server raised an exception: {} {}\n""".format(r_,e,_nc))
            input("Press a key to continue...")
            print(" ")
            return
        except WindowsError:
            print("""
{}<ERROR>
The server raised an exception.\n""")
            input("Press a key to continue...")
            print(" ")
            return

    if protvar == "smb":
        try:
            smbhandle = urllib.request.build_opener(SMBHandler)
            if plat_type == 'Linux':
                os.system('setterm -cursor off')
            for g in fileglob:
                if os.path.isdir(g):
                    continue
                gfile = str(os.path.basename(g))
                file = open(g, 'rb')
                print("Sending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,servvar,_nc,p_,remdirvar,_nc,y_,protvar.upper(),_nc))
                sizedisplay = "Size: "+str(os.path.getsize(g))+" bytes("+str(round(float(os.path.getsize(g))/pow(2, 20), 2))+" MB) ||"
                spinner = Halo(text=sizedisplay, placement='right', color='yellow', spinner='dots')
                spinner.start()
                u = smbhandle.open('smb://{}:{}@{}{}{}'.format(uservar,passvar,servvar,remdirvar,gfile), data = file)
                if plat_type == 'Windows':
                    spinner.stop_and_persist('√', sizedisplay + ' Transfer complete.')
                elif plat_type == 'Linux':
                    spinner.succeed(sizedisplay + ' Transfer complete.')
                file.close()
                print("\n")
            if plat_type == 'Linux':
                os.system('setterm -cursor on')
            print("\n")
        except (socket.gaierror, socket.timeout):
            spinner.stop()
            print("""
{}<ERROR>
Server is offline, unavailable, or otherwise not responding. Check the hostname or IP and try again.{}\n""".format(r_,_nc))
            input("Press a key to continue...")
            print(" ")
            return

    if protvar == "s3":
        try:
            s3 = boto3.client('s3')
            if plat_type == 'Linux':
                os.system('setterm -cursor off')
            for g in fileglob:
                if os.path.isdir(g):
                    continue
                gfile = str(os.path.basename(g))
                global s3_f_size
                s3_f_size = os.path.getsize(g)
                global s3_bytes
                s3_bytes = 0
                print("Sending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,'s3://',_nc,p_,remdirvar,_nc,y_,'HTTPS',_nc))
                s3.upload_file(g, remdirvar, gfile, Callback=s3bar)
                print("\n\n")
            if plat_type == 'Linux':
                os.system('setterm -cursor on')
        except NoCredentialsError:
            print("""
{}Could not determine valid credentials for AWS{}.

AWS credentials are retrieved automatically by boto3 (the library used to interact with S3) in a number of ways.
It is simplest and recommended to install {}awscli{} for your platform, but there are other options.

Refer to the boto3 documentation on the topic here:
https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html

To install {}awscli{} through Python:

pip install awscli\n""".format(r_,_nc,y_,_nc,y_,_nc))

            input("Press a key to continue...")
            print(" ")
            return
        except ClientError as e:
            if e.response['Error']['Code'] == "NoSuchBucket" or "AccessDenied":
                print("""
{}<ERROR>
Bucket name doesn't exist or access was denied. Check the bucket name and your permissions and try again.{}
        """.format(r_,_nc))
                input("Press a key to continue...")
                print(" ")
                return
            elif e.response['Error']['Code'] != "":
                print("""
{}<ERROR>
Unknown error. Check your credentials and bucketname and try again.{}
    """.format(r_,_nc))
                input("Press a key to continue...")
                print(" ")
                return

# Single destination upload function
def mpfuUpload():

    protPrompt()

    # Pull in last connected server variable, prompt for current server, update sav.mpfu with current server
    global lastserv
    if protvar == "s3":
        return s3Upload()
    else:
        # Deduplicate previous connection list and prepare for tab completion
        sav = open('sav.mpfu')
        sav_f = sav.readlines()
        sav.close()
        dedupe_f = []
        for f in sav_f:
            dedupe_f.append(f.strip())
        tabsrvlist = set(dedupe_f)
        sav_again = open('sav.mpfu', 'w')
        for line in tabsrvlist:
            sav_again.write(line.strip() + "\n")
        sav_again.close()

        # Allow tab completion of previous connections
        t.createListCompleter(tabsrvlist)
        readline.set_completer(t.listCompleter)

        servprompt = "\nServer IP or hostname (Leave blank for last connected: [{}{}{}]): ".format(b_,lastserv,_nc)
        servvar = input(servprompt).strip()
        if servvar == "":
            servvar = lastserv
        lastserv_u = open('sav.mpfu', 'a')
        lastserv_u.write(servvar)
        lastserv_u.close()
        lastserv = servvar
    if protvar != "s3":

        credPrompt()

        if protvar == "sftp":
            remdirvar = input("\nRemote upload directory (remote dir MUST be specified AND include leading and trailing slash): ")
        elif protvar == "smb":
            print("\nRemote upload share (input name of share with forward slashes, i.e. {}/network/share/{}): ".format(p_,_nc), end="")
            remdirvar = input()
        else:
            remdirvar = input("\nRemote upload directory (include leading and trailing slash, or leave blank for default): ")

    localfsPrompt()

    finalUpload(protvar,servvar,uservar,passvar,dirvar,filevar,remdirvar)

def s3Upload():
    remdirvar = input("\nBucket name (without formatting, i.e. s3bucketname): ")
    servvar = "s3://"
    uservar = ""
    passvar = ""
    try:
        s3 = boto3.client('s3')
        s3.list_objects(Bucket=remdirvar, MaxKeys=1)
    except NoCredentialsError:
        print("""
{}Could not determine valid credentials for AWS{}.

AWS credentials are retrieved automatically by boto3 (the library used to interact with S3) in a number of ways.
It is simplest and recommended to install {}awscli{} for your platform, but there are other options.

Refer to the boto3 documentation on the topic here:
https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html

To install {}awscli{} through Python:

pip install awscli\n""".format(r_,_nc,y_,_nc,y_,_nc))

        input("Press a key to return to the menu...")
        print(" ")
        return
    except ClientError as e:
        if e.response['Error']['Code'] == "NoSuchBucket" or "AccessDenied":
            print("""
Bucket name {}doesn't exist{} or {}access was denied{}. Check the bucket name and your permissions and try again.
    """.format(r_,_nc,r_,_nc))
            input("Press a key to return to the menu...")
            print(" ")
            return
        elif e.response['Error']['Code'] != "":
            print("""
Unknown {}error{}. Check your credentials and bucketname and try again.
""".format(r_,_nc))
            input("Press a key to return to the menu...")
            print(" ")
            return

    localfsPrompt()

    finalUpload(protvar,servvar,uservar,passvar,dirvar,filevar,remdirvar)

# MPFU multi-file upload function
def mpfuMultiUpload():
    print("""

You can upload one or more local files to a list of remote servers.
Please input the list in the following format. You can list several destinations separated by commas,
and with all elements separated by colons:

FTP, SFTP, SCP, and SMB:
{}protocol{}:{}IP or hostname{}:{}/remotepath/{}:{}login{}:{}password{}

AWS S3:
{}s3{}:{}bucketname{}

Enter server list in the format above:""".format(g_,_nc,b_,_nc,p_,_nc,y_,_nc,y_,_nc,g_,_nc,p_,_nc))
    inputlistvar = input("> ")

    localfsPrompt()

    # Loop through input list and parse into variables
    split_input = inputlistvar.split(",")
    for e in range(len(split_input)):
        pop_input = split_input.pop()
        elem = pop_input.split(":")
        protvar = elem[0].strip()
        if protvar != "s3":
            servvar = elem[1].strip()
            remdirvar = elem[2].strip()
            uservar = elem[3].strip()
            passvar = elem[4].strip()
        if protvar == "s3":
            remdirvar = elem[1].strip()

        # Perform uploads
        if protvar != "s3":
            print("Starting transfers to {}{}{}: \n".format(b_,servvar,_nc))
        if protvar == "s3":
            print("Starting transfers to {}{}{}:{}{}{}: \n".format(y_,'s3://',_nc,p_,remdirvar,_nc))
            servvar, uservar, passvar = (" ", " ", " ")
        finalUpload(protvar,servvar,uservar,passvar,dirvar,filevar,remdirvar)

# MPFU multi-file upload to destination list file
def mpfuMultiUploadFile():
    # If serverlist file NOT supplied as CLI argument
    if len(sys.argv) == 1:
        print("\n{}No server list file provided{}. Please run the utility with the server list text file provided as an argument: {}mpfu{} {}serverlist{}".format(r_,_nc,b_,_nc,y_,_nc))
        print("""
Server list file must be text in the following format, one entry per line:

FTP, SFTP, SCP, and SMB:
{}protocol{}:{}IP or hostname{}:{}/remotepath/{}:{}login{}:{}password{}

AWS S3:
{}s3{}:{}bucketname{}
""".format(g_,_nc,b_,_nc,p_,_nc,y_,_nc,y_,_nc,g_,_nc,p_,_nc))
        input("Press a key to return to the menu...")
        print(" ")
        return
    elif len(sys.argv) == 2:
        with open(sys.argv[1], 'r') as serv_file:
            ufile_input = serv_file.read()
            sfile_input = ufile_input.strip()

            localfsPrompt()

            # Loop through input list and parse into variables
            split_input = sfile_input.split("\n")
            for e in range(len(split_input)):
                pop_input = split_input.pop()
                elem = pop_input.split(":")
                protvar = elem[0].strip()
                if protvar != "s3":
                    servvar = elem[1].strip()
                    remdirvar = elem[2].strip()
                    uservar = elem[3].strip()
                    passvar = elem[4].strip()
                if protvar == "s3":
                    remdirvar = elem[1].strip()
                    servvar = ""
                    uservar = ""
                    passvar = ""

                # Perform uploads
                if protvar != "s3":
                    print("Starting transfers to {}{}{}: \n".format(b_,servvar,_nc))
                if protvar == "s3":
                    print("Starting transfers to {}{}{}:{}{}{}: \n".format(y_,'s3://',_nc,p_,remdirvar,_nc))
                finalUpload(protvar,servvar,uservar,passvar,dirvar,filevar,remdirvar)

# MPFU menu function
def mpfuMenu():
    bashCompleter()
    print("""
	 {}__  __ _____  ______ _    _
	|  \\/  |  __ \\|  ____| |  | |
	| \\  / | |__) | |__  | |  | |
	| |\\/| |  ___/|  __| | |  | |
	| |  | | |    | |    | |__| |
	|_|  |_|_|    |_|     \\____/{}""".format(bld_,_nc))
    print("""
     -=|Multi-Protocol File Uploader|=-

 {}|Upload|{}

 1) Upload local files to {}one{} destination (server, share, bucket, etc.)
 2) Upload local files to {}multiple{} destinations from manual INPUT
 3) Upload local files to {}multiple{} destinations from a {}list{} entered at CLI (./mpfu.py <filename>)\n
 q) Quit\n\n""".format(bld_,_nc,y_,_nc,y_,_nc,y_,_nc,y_,_nc))

    choicevar = input("Select an option [1-3, q]: ")

    if choicevar == "1":
        mpfuUpload()
    elif choicevar == "2":
        mpfuMultiUpload()
    elif choicevar == "3":
        mpfuMultiUploadFile()
    elif choicevar == "q" or "Q":
        print("\n")
        sys.exit()
    else:
        print("\n{}Not an option!{}".format(r_,_nc))

menuloop = 1
while menuloop == 1:
    mpfuMenu()
