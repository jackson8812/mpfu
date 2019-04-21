#!/usr/bin/env python3

import os
import sys
import platform
import socket
import getpass
import glob
import paramiko
import warnings
import urllib
import argparse

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

# Homepath of script
homepath = os.path.abspath(os.path.dirname(__file__))

# CLI arguments
parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('-l','--list', required=False, help="""
A list of servers to upload files and/or issue SSH commands to may be provided when running MPFU.
Provide the serverlist as a text file, with one server per line in the following format:

protocol:Destination IP or hostname:/remote/upload/path/:username:password 

""")
args = parser.parse_args()

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
warnings.filterwarnings(action='ignore', module='.*paramiko.*')

# Tab completion code from https://gist.github.com/iamatypeofwalrus/5637895
class tabCompleter(object):

    def pathCompleter(self, text, state):
        line = readline.get_line_buffer().split()

        # replace ~ with the user's home dir. See https://docs.python.org/2/library/os.path.html
        if '~' in text:
            text = os.path.expanduser('~')

        # autocomplete directories with having a trailing slash
        if os.path.isdir(text) and text[-1] != "\\" and text[-1] != "/":
            if plat_type == 'Linux':
                text += '/'
            elif plat_type == 'Windows':
                text += '\\'

        return [x for x in glob.glob(text + '*')][state]

    def createListCompleter(self, ll):
        def listCompleter(text, state):
            line = readline.get_line_buffer()
            lc = line.split()

            if not line:
                return [c + " " for c in ll][state]

            elif line.startswith('./'):
                scrubline = line.replace('./', '')
                return ['./' + c for c in ll if c.startswith(scrubline)][state]

            elif '@' in line:
                scrubline = line.split('@')
                return [scrubline[0].strip() + '@' + c.strip() for c in ll if c.startswith(scrubline[1])][state]

            elif " " in line:
                return [" ".join(lc[:-1]) + " "  + c.strip() for c in ll if c.startswith(lc[-1])][state]

            else:
                return [c + " " for c in ll if c.startswith(line)][state]

        self.listCompleter = listCompleter

# Function that enables above tab completer
def bashCompleter():
    global t
    t = tabCompleter()
    t.createListCompleter(["ab", "aa", "bcd", "bdf"])

    readline.set_completer_delims('\t')
    readline.parse_and_bind("tab: complete")

    readline.set_completer(t.pathCompleter)

def lastServ():
    # Try load in last server connection from sav.mpfu, if doesn't exist create it
    try:
        with open(os.path.join(homepath, 'sav.mpfu')) as f:
            lastserv_f = f.readlines()
            lastserv = lastserv_f[-1].strip()
    except IOError:
        with open(os.path.join(homepath, 'sav.mpfu'), 'w') as lastserv_f:
            lastserv = ""
    except IndexError:
        lastserv = ""
    return lastserv, lastserv_f

# Prompt for server to connect to
def servPrompt():
    lastserv, lastserv_f = lastServ()

    # Deduplicate previous connection list and prepare for tab completion
    with open(os.path.join(homepath, 'sav.mpfu')) as sav:
        sav_f = sav.readlines()
    dedupe_f = [f.strip() for f in sav_f]
    tabsrvlist = set(dedupe_f)
    with open(os.path.join(homepath, 'sav.mpfu'), 'w') as sav_again:
        for line in tabsrvlist:
            sav_again.write(line.strip() + "\n")

    # Allow tab completion of previous connections
    t.createListCompleter(tabsrvlist)
    readline.set_completer(t.listCompleter)

    servprompt = f"\nServer IP or hostname (Leave blank for last connected: [{b_}{lastserv}{_nc}]): "
    servvar = input(servprompt).strip()
    if servvar == "":
        servvar = lastserv
    with open(os.path.join(homepath, 'sav.mpfu'), 'a') as lastserv_u:
        lastserv_u.write(servvar)
    lastserv = servvar
    return servvar

# Protocol prompt function
def protPrompt():
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
        print(f"\nNote: {y_}FTP{_nc} protocol is inherently {r_}insecure{_nc}, your password will be encrypted, but file(s) are sent unencrypted!\n")
    elif protvar == "smb":
        print(f"\n{r_}!!!WARNING!!!{_nc} This utility will overwrite any file(s) on the share with same name as the uploaded file(s). {y_}USE CAUTION!{_nc}")
    return protvar

# Credentials prompt function
def credPrompt():
    uservar = input("\nUsername: ")

    passvar = getpass.getpass("\nPassword: ")

    creds = uservar, passvar

    return creds

# Prompt for local dir and file(s) function
def localfsPrompt():
    readline.set_completer(t.pathCompleter)
    if plat_type == 'Linux':
        dirinput = "\nLocal directory containing files to upload (include leading slash): "
    elif plat_type == 'Windows':
        dirinput = "\nLocal directory containing files to upload (include drive, i.e. C:\\upload\\directory\\): "
    dirvar = input(dirinput)
    filevar = ""

    # If full path is entered (with * for file), this block handles that case.
    if dirvar.endswith('*'):
        scrubdir = dirvar.replace('\\\\', '/').replace('\\', '/')
        filevar = scrubdir.split('/')[-1]
        dirvar = os.path.dirname(dirvar.replace('*',''))
        # Pull path list into a glob for parsing
        fileglob = glob.glob(os.path.join(dirvar, filevar.strip()))
        fs = dirvar, filevar, fileglob
        print(" ")
        return fs
    # If full path (including file) is entered, this block handles that case.
    if os.path.isfile(dirvar):
        filevar = os.path.basename(dirvar)
        dirvar = os.path.dirname(dirvar)
        # Pull path list into a glob for parsing
        fileglob = glob.glob(os.path.join(dirvar, filevar.strip()))
        fs = dirvar, filevar, fileglob
        print(" ")
        return fs

    print("\nContents of directory: \n")

    # Filter subdirectories out of directory contents
    dirvarlist = os.listdir(dirvar)
    for file in dirvarlist:
        dirvaritem = os.path.join(dirvar, file)
        if os.path.isdir(dirvaritem):
            dirvarlist.remove(file)
    dirlist = '\n'.join(map(str, dirvarlist))
    print(dirlist)

    # Feed directory contents list into tab completer
    t.createListCompleter(dirvarlist)
    readline.set_completer(t.listCompleter)
    filevar = input("\nFile(s) to upload (wildcards accepted): ")
    print("")
    # Pull path list into a glob for parsing
    fileglob = glob.glob(os.path.join(dirvar, filevar.strip()))
    fs = dirvar, filevar, fileglob
    return fs

# Modified progress provider for SCP. fname parameter added but left blank to align with scp module callback output
# Annoyingly must be in global namespace because it's called by connection, not transfer
def sbar(fname, total_bytes, transfered_bytes):
    bar_length = 35
    percent = float(transfered_bytes) / total_bytes
    hashes = '#' * int(round(percent * bar_length))
    spaces = ' ' * (bar_length - len(hashes))
    message = "\rSize: " + str(total_bytes) + " bytes("\
        + str(round(float(total_bytes) / pow(2, 20), 2)) + " MB)"
    message += " || Amount of file transferred: [{}] {}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
    if transfered_bytes == total_bytes:
        message = "\rSize: " + str(total_bytes) + " bytes("\
            + str(round(float(total_bytes) / pow(2, 20), 2)) + " MB)"
        message += " || File transferred. [{}] {}%                    \r"\
            .format(hashes + spaces, round(percent * 100, 2))
    sys.stdout.write(message)
    sys.stdout.flush()


# Single destination upload function. Routes to protocol-specific upload worker functions.
def mpfuUpload():

    protvar = protPrompt()

    if protvar == "ftp":
        protvar = "ftp"
        servvar = servPrompt()

        uservar, passvar = credPrompt()

        remdirvar = input(
        "\nRemote upload directory (include leading and trailing slash, or leave blank for default): ")

        dirvar, filevar, fileglob = localfsPrompt()

        return ftpUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob)

    elif protvar == "sftp":
        protvar = "sftp"
        servvar = servPrompt()

        uservar = input("\nUsername: ")

        try:
            pssh = paramiko.SSHClient()
            pssh.load_system_host_keys()
            pssh.set_missing_host_key_policy(paramiko.WarningPolicy())
            pssh.connect(hostname=servvar, username=uservar,
                        timeout=8)
            passvar = ""
            sftpc = pssh.open_sftp()
        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.SSHException):
            print(
                f"\n{y_}No SSH key matching this host to authenticate with.{_nc}\n\nEnter password for {y_}{uservar}{_nc}: ", end=" ")
            
            # print(f"Enter password for {y_}{uservar}{_nc}", end=": ")
            
            passvar = getpass.getpass('')

            pssh = paramiko.SSHClient()
            pssh.load_system_host_keys()
            pssh.set_missing_host_key_policy(paramiko.WarningPolicy())
            pssh.connect(hostname=servvar, username=uservar, password=passvar,
                        timeout=8)
            sftpc = pssh.open_sftp()

        remdirvar = input(
            "\nRemote upload directory (remote dir must be specified with leading and trailing slash): ")

        dirvar, filevar, fileglob = localfsPrompt()

        return sftpUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob, sftpc)

    elif protvar == "scp":

        protvar = "scp"
        servvar = servPrompt()

        uservar = input("\nUsername: ")

        import scp

        try:
            pssh = paramiko.SSHClient()
            pssh.load_system_host_keys()
            pssh.set_missing_host_key_policy(paramiko.WarningPolicy())
            pssh.connect(hostname=servvar, username=uservar,
                        timeout=8)
            passvar = ""
            pscp = scp.SCPClient(pssh.get_transport(), progress=sbar)
        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.SSHException):
            print(
                f"\n{y_}No SSH key matching this host to authenticate with.{_nc}\n\nEnter password for {y_}{uservar}{_nc}: ", end=" ")
            passvar = getpass.getpass('')

            pssh = paramiko.SSHClient()
            pssh.load_system_host_keys()
            pssh.set_missing_host_key_policy(paramiko.WarningPolicy())
            pssh.connect(hostname=servvar, username=uservar, password=passvar,
                        timeout=8)
            pscp = scp.SCPClient(pssh.get_transport(), progress=sbar)

        remdirvar = input(
            "\nRemote upload directory (remote dir must be specified with leading and trailing slash): ")

        dirvar, filevar, fileglob = localfsPrompt()

        return scpUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob, pscp)

    
    elif protvar == "smb":
        protvar = "smb"

        smbprompt = f"\nEnter server and share for upload (e.g. {p_}\\\\fileserver.name.net\\network\\share\\{_nc}): "

        smb_info = input(smbprompt).replace(
            '\\\\', '/').replace('\\', '/').split('/')

        servvar = smb_info[1]
        remdirvar = '/' + '/'.join(smb_info[2:])

        uservar, passvar = credPrompt()

        dirvar, filevar, fileglob = localfsPrompt()

        return smbUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob)

    elif protvar == "s3":
        import boto3
        from botocore.exceptions import NoCredentialsError, ClientError

        protvar = "s3"
        remdirvar = input(
            "\nBucket name (without formatting, i.e. s3bucketname): ")
        servvar = "s3://"
        try:
            # Make sure bucket exists and we can connect
            s3 = boto3.client('s3')
            s3.list_objects(Bucket=remdirvar, MaxKeys=1)
        except NoCredentialsError:
            print(f"""
    {r_}Could not determine valid credentials for AWS{_nc}.

    AWS credentials are retrieved automatically by boto3 (the library used to interact with S3) in a number of ways.
    It is simplest and recommended to install {y_}awscli{_nc} for your platform, but there are other options.

    Refer to the boto3 documentation on the topic here:
    https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html

    To install {y_}awscli{_nc} through Python:

    pip install awscli\n""")

            input("Press a key to return to the menu...")
            print(" ")
            return
        except ClientError as e:
            if e.response['Error']['Code'] == "NoSuchBucket" or "AccessDenied":
                print(f"""
    Bucket name {r_}doesn't exist{_nc} or {r_}access was denied{_nc}. Check the bucket name and your permissions and try again.
        """)
                input("Press a key to return to the menu...")
                print(" ")
                return
            elif e.response['Error']['Code'] != "":
                print(f"""
    Unknown {r_}error{_nc}. Check your credentials and bucketname and try again.
    """)
                input("Press a key to return to the menu...")
                print(" ")
                return

        dirvar, filevar, fileglob = localfsPrompt()

        return s3Upload(dirvar, filevar, fileglob, remdirvar)


# fbar_bytes initialized in global namespace to make fbar() work
fbar_bytes = 0

def ftpUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob):
    import ftplib

    # Modified progress provider for ftplib. fbar_bytes set to 0 initially to make func work
    def fbar(ftpbytes):
        global fbar_bytes
        total_bytes = bar_f_size
        fbar_bytes += 8192
        bar_length = 35
        percent = float(fbar_bytes) / total_bytes
        hashes = '#' * int(round(percent * bar_length))
        spaces = ' ' * (bar_length - len(hashes))
        message = "\rSize: " + str(total_bytes) + " bytes("\
                + str(round(float(total_bytes) / pow(2, 20), 2)) + " MB)"
        message += " || Amount of file transferred: [{0}] {1}%\r".format(hashes + spaces,
                                                                        round(percent * 100, 2))
        if fbar_bytes >= total_bytes:
            message = "\rSize: " + str(total_bytes) + " bytes("\
                    + str(round(float(total_bytes) / pow(2, 20), 2)) + " MB)"
            message += " || File transferred. [{0}] {1}%                    \r"\
                    .format(hashes + spaces, round(percent * 100))
            fbar_bytes = 0
        sys.stdout.write(message)
        sys.stdout.flush()
    try:
        session = ftplib.FTP_TLS()
        session.connect(servvar, 21)
        session.sendcmd(f'USER {uservar}')
        session.sendcmd(f'PASS {passvar}')
        if remdirvar != "":
            session.sendcmd(f'cwd {remdirvar}')
        resp_pwd = session.sendcmd('pwd')
        ftp_pwd = resp_pwd.lstrip('0123456789" ').rstrip('"')
        if plat_type == 'Linux':
            os.system('setterm -cursor off')
        for g in fileglob:
            if os.path.isdir(g):
                continue
            gfile = str(os.path.basename(g))
            file = open(f'{g}', 'rb')
            global bar_f_size
            global transfered_bytes
            transfered_bytes = 0
            bar_f_size = os.path.getsize(g)
            if remdirvar == "":
                remdirvar = "[default]"
            print(
                f"Sending {g_}{g}{_nc} to {b_}{servvar}{_nc}:{p_}{ftp_pwd}{_nc} over {y_}{protvar.upper()}{_nc} =>")
            session.storbinary('STOR ' + gfile, file, callback=fbar)
            print("\n\n")
            file.close()
        session.quit()
        if plat_type == 'Linux':
            os.system('setterm -cursor on')
    except ftplib.all_errors as e:
        print(f"""
{r_}<ERROR>
The server raised an exception: {e} {_nc}\n""")
        input("Press a key to continue...")
        print(" ")
        return


def sftpUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob, sftpc):

    # Transfer progress provider from https://github.com/jonDel/ssh_paramiko
    def pbar(transfered_bytes, total_bytes):
        bar_length = 35
        percent = float(transfered_bytes) / total_bytes
        hashes = '#' * int(round(percent * bar_length))
        spaces = ' ' * (bar_length - len(hashes))
        message = "\rSize: " + str(total_bytes) + " bytes("\
                + str(round(float(total_bytes) / pow(2, 20), 2)) + " MB)"
        message += " || Amount of file transferred: [{0}] {1}%\r".format(hashes + spaces,
                                                                        round(percent * 100, 2))
        if transfered_bytes == total_bytes:
            message = "\rSize: " + str(total_bytes) + " bytes("\
                    + str(round(float(total_bytes) / pow(2, 20), 2)) + " MB)"
            message += " || File transferred. [{0}] {1}%                    \r"\
                    .format(hashes + spaces, round(percent * 100, 2))
        sys.stdout.write(message)
        sys.stdout.flush()

    try:
        if plat_type == 'Linux':
            os.system('setterm -cursor off')
        for g in fileglob:
            if os.path.isdir(g):
                continue
            gfile = str(os.path.basename(g))
            print(f"Sending {g_}{g}{_nc} to {b_}{servvar}{_nc}:{p_}{remdirvar}{_nc} over {y_}{protvar.upper()}{_nc} =>")
            sftpc.put(g, remdirvar + gfile, callback=pbar)
            print("\n\n")
        sftpc.close()
        if plat_type == 'Linux':
            os.system('setterm -cursor on')
    except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.BadAuthenticationType):
        print(f"""
{r_}<ERROR>
Username, password, or SSH key are incorrect, or the server is not accepting the type of authentication attempted{_nc}.\n""")
        input("Press a key to continue...")
        print(" ")
        return
    except (BlockingIOError, socket.timeout):
        print(f"""
{r_}<ERROR>
Server is offline, unavailable, or otherwise not responding. Check the hostname or IP and try again.{_nc}\n""")
        input("Press a key to continue...")
        print(" ")
        return
    except socket.gaierror as e:
        print(f"""
{r_}<ERROR>
The server raised an exception: {e} {_nc}\n""")
        input("Press a key to continue...")
        print(" ")
        return

    
def scpUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob, pscp):

    try:
        if plat_type == 'Linux':
            os.system('setterm -cursor off')
        for g in fileglob:
            if os.path.isdir(g):
                continue
            gfile = str(os.path.basename(g))
            print(
                f"Sending {g_}{g}{_nc} to {b_}{servvar}{_nc}:{p_}{remdirvar}{_nc} over {y_}{protvar.upper()}{_nc} =>")
            pscp.put(g, remote_path=remdirvar)
            print("\n\n")
        pscp.close()
        if plat_type == 'Linux':
            os.system('setterm -cursor on')
    except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.BadAuthenticationType):
        print(f"""
{r_}<ERROR>
Username, password, or SSH key are incorrect, or the server is not accepting the type of authentication attempted{_nc}.\n""")
        input("Press a key to continue...")
        print(" ")
        return
    except (BlockingIOError, socket.timeout):
        print(f"""
{r_}<ERROR>
Server is offline, unavailable, or otherwise not responding. Check the hostname or IP and try again.{_nc}\n""")
        input("Press a key to continue...")
        print(" ")
        return
    except scp.SCPException as e:
        print(f"""
{r_}<ERROR>
The server raised an exception: {e} {_nc}\n""")
        input("Press a key to continue...")
        print(" ")
        return
    except socket.gaierror as e:
        print(f"""
{r_}<ERROR>
The server raised an exception: {e} {_nc}\n""")
        input("Press a key to continue...")
        print(" ")
        return

def smbUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob):
    from smb.SMBConnection import SMBConnection
    from smb.smb_structs import OperationFailure
    from halo import Halo

    try:
        # Sanitize username in case of domain inclusion
        if "\\" in uservar:
            uservar = uservar.split("\\")[1]
            domain = uservar.split("\\")[0]

        # Get local hostname and remote IP for pysmb
        host_n = socket.gethostname()
        target_ip = socket.gethostbyname(servvar)

        # Fake a NetBIOS name
        netbios_n = servvar.split('.')
        netbios_n = netbios_n[0].upper()

        # Extract service name from input
        share_n = remdirvar.replace(
            '\\\\', '/').replace('\\', '/').split('/')[1].replace('/', '')

        # Extract path from input
        path_n = remdirvar.replace(
            '\\\\', '/').replace('\\', '/').split('/')[2:]
        path_n = '/' + '/'.join(path_n)

        # Establish actual SMB connection
        smbc = SMBConnection(uservar, passvar, host_n,
                                netbios_n, use_ntlm_v2=True, is_direct_tcp=True)
        assert smbc.connect(target_ip, 445)

        if plat_type == 'Linux':
            os.system('setterm -cursor off')
        for g in fileglob:
            if os.path.isdir(g):
                continue
            gfile = str(os.path.basename(g))
            print(
                f"Sending {g_}{g}{_nc} to {b_}{servvar}{_nc}:{p_}{remdirvar}{_nc} over {y_}{protvar.upper()}{_nc} =>")
            sizedisplay = "Size: " + str(os.path.getsize(g)) + " bytes(" + str(
                round(float(os.path.getsize(g)) / pow(2, 20), 2)) + " MB) ||"
            spinner = Halo(text=sizedisplay, placement='right',
                            color='yellow', spinner='dots')
            spinner.start()
            with open(g, 'rb') as file:
                smbc.storeFile(share_n, path_n + gfile, file, timeout=15)

            if plat_type == 'Windows':
                spinner.stop_and_persist(
                    '√', sizedisplay + ' Transfer complete.')
            elif plat_type == 'Linux':
                spinner.succeed(sizedisplay + ' Transfer complete.')
            print("\n")
        if plat_type == 'Linux':
            os.system('setterm -cursor on')
        print("\n")
    except (socket.gaierror, socket.timeout):
        print(f"""
{r_}<ERROR>
Server is offline, unavailable, or otherwise not responding. Check the hostname or IP and try again.{_nc}\n""")
        input("Press a key to continue...")
        print(" ")
        return

    except OperationFailure:
        print(f"""
{r_}<ERROR>
Unable to connect to share. Permissions may be invalid or share name may be wrong.
Please use the following format (do NOT include server name): {p_}/share/path/to/target/ {_nc}\n""")
        input("Press a key to continue...")
        print(" ")
        return


def s3Upload(dirvar, filevar, fileglob, remdirvar):

    import boto3
    from botocore.exceptions import NoCredentialsError, ClientError

    # Modified progress provider for S3. boto3 only sends transferred bytes each update.
    def s3bar(t_bytes):
        global s3_bytes
        s3_bytes += t_bytes
        bar_length = 35
        percent = float(s3_bytes) / s3_f_size
        hashes = '#' * int(round(percent * bar_length))
        spaces = ' ' * (bar_length - len(hashes))
        message = "\rSize: " + str(s3_f_size) + " bytes("\
                + str(round(float(s3_f_size) / pow(2, 20), 2)) + " MB)"
        message += " || Amount of file transferred: [{}] {}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
        if s3_bytes == s3_f_size:
            message = "\rSize: " + str(s3_f_size) + " bytes("\
                    + str(round(float(s3_f_size) / pow(2, 20), 2)) + " MB)"
            message += " || File transferred. [{}] {}%                    \r"\
                    .format(hashes + spaces, round(percent * 100, 2))
        sys.stdout.write(message)
        sys.stdout.flush()

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
            print(
                f"Sending {g_}{g}{_nc} to {b_}s3://{_nc}:{p_}{remdirvar}{_nc} over {y_}HTTPS{_nc} =>")
            s3.upload_file(g, remdirvar, gfile, Callback=s3bar)
            print("\n\n")
        if plat_type == 'Linux':
            os.system('setterm -cursor on')
    except NoCredentialsError:
        print(f"""
{r_}Could not determine valid credentials for AWS{_nc}.

AWS credentials are retrieved automatically by boto3 (the library used to interact with S3) in a number of ways.
It is simplest and recommended to install {y_}awscli{_nc} for your platform, but there are other options.

Refer to the boto3 documentation on the topic here:
https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html

To install {y_}awscli{_nc} through Python:

pip install awscli\n""")

        input("Press a key to continue...")
        print(" ")
        return
    except ClientError as e:
        if e.response['Error']['Code'] == "NoSuchBucket" or "AccessDenied":
            print(f"""
{r_}<ERROR>
Bucket name doesn't exist or access was denied. Check the bucket name and your permissions and try again.{_nc}
    """)
            input("Press a key to continue...")
            print(" ")
            return
        elif e.response['Error']['Code'] != "":
            print(f"""
{r_}<ERROR>
Unknown error. Check your credentials and bucketname and try again.{_nc}
""")
            input("Press a key to continue...")
            print(" ")
            return

# MPFU multi-file upload function
def mpfuMultiUpload():
    print(f"""

You can upload one or more local files to a list of remote servers.
Please input the list in the following format. You can list several destinations separated by commas,
and with all elements separated by colons:

FTP, SFTP, SCP, and SMB:
{g_}protocol{_nc}:{b_}IP or hostname{_nc}:{p_}/remotepath/{_nc}:{y_}login{_nc}:{y_}password{_nc}

AWS S3:
{g_}s3{_nc}:{p_}bucketname{_nc}

Enter server list in the format above:""")
    inputlistvar = input("> ")

    dirvar, filevar, fileglob = localfsPrompt()

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
        if protvar == "ftp":
            print(f"Starting transfers to {b_}{servvar}{_nc}: \n")
            ftpUpload(protvar, servvar, uservar, passvar, dirvar, filevar, remdirvar, fileglob)
        elif protvar == "sftp":
            pssh=paramiko.SSHClient()
            pssh.load_system_host_keys()
            pssh.set_missing_host_key_policy(
                paramiko.WarningPolicy())
            print(f"Starting transfers to {b_}{servvar}{_nc}: \n")
            pssh.connect(hostname=servvar, username=uservar, password=passvar,
                        timeout=8)
            sftpc=pssh.open_sftp()
            sftpUpload(protvar, servvar, uservar, passvar,
                        dirvar, filevar, remdirvar, fileglob, sftpc)
        elif protvar == "scp":
            import scp
            pssh=paramiko.SSHClient()
            pssh.load_system_host_keys()
            pssh.set_missing_host_key_policy(paramiko.WarningPolicy())
            pssh.connect(hostname=servvar, username=uservar, password=passvar,
                         timeout=8)
            pscp=scp.SCPClient(pssh.get_transport(), progress=sbar)
            print(f"Starting transfers to {b_}{servvar}{_nc}: \n")
            scpUpload(protvar, servvar, uservar, passvar,
                      dirvar, filevar, remdirvar, fileglob, pscp)
        elif protvar == "smb":
            print(f"Starting transfers to {b_}{servvar}{_nc}: \n")
            smbUpload(protvar, servvar, uservar, passvar,
                      dirvar, filevar, remdirvar, fileglob)
        if protvar == "s3":
            print(f"Starting transfers to {y_}s3://{_nc}:{p_}{remdirvar}{_nc}: \n")
            servvar, uservar, passvar = (" ", " ", " ")
            s3Upload(dirvar, filevar, fileglob, remdirvar)

# MPFU multi-file upload to destination list file
def mpfuMultiUploadFile():
    # If serverlist file NOT supplied as CLI argument
    if not args.list:
        print(f"\n{r_}No server list file provided{_nc}. Please run the utility "
        f"with the server list text file provided as an argument: {b_}mpfu{_nc} {y_}- l serverlist.txt{_nc}")
        print(f"""
Server list file must be text in the following format, one entry per line:

FTP, SFTP, SCP, and SMB:
{g_}protocol{_nc}:{b_}IP or hostname{_nc}:{p_}/remotepath/{_nc}:{y_}login{_nc}:{y_}password{_nc}

AWS S3:
{g_}s3{_nc}:{p_}bucketname{_nc}
""")
        input("Press a key to return to the menu...")
        print(" ")
        return
    elif args.list:
        with open(args.list, 'r') as serv_file:
            ufile_input = serv_file.read()
            sfile_input = ufile_input.strip()

            dirvar, filevar, fileglob = localfsPrompt()

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
                if protvar == "ftp":
                    print(f"Starting transfers to {b_}{servvar}{_nc}: \n")
                    ftpUpload(protvar, servvar, uservar, passvar,
                            dirvar, filevar, remdirvar, fileglob)
                elif protvar == "sftp":
                    pssh = paramiko.SSHClient()
                    pssh.load_system_host_keys()
                    pssh.set_missing_host_key_policy(
                        paramiko.WarningPolicy())
                    print(f"Starting transfers to {b_}{servvar}{_nc}: \n")
                    pssh.connect(hostname=servvar, username=uservar, password=passvar,
                                timeout=8)
                    sftpc = pssh.open_sftp()
                    sftpUpload(protvar, servvar, uservar, passvar,
                            dirvar, filevar, remdirvar, fileglob, sftpc)
                elif protvar == "scp":
                    import scp
                    pssh = paramiko.SSHClient()
                    pssh.load_system_host_keys()
                    pssh.set_missing_host_key_policy(paramiko.WarningPolicy())
                    pssh.connect(hostname=servvar, username=uservar, password=passvar,
                                timeout=8)
                    pscp = scp.SCPClient(pssh.get_transport(), progress=sbar)
                    print(f"Starting transfers to {b_}{servvar}{_nc}: \n")
                    scpUpload(protvar, servvar, uservar, passvar,
                            dirvar, filevar, remdirvar, fileglob, pscp)
                elif protvar == "smb":
                    print(f"Starting transfers to {b_}{servvar}{_nc}: \n")
                    smbUpload(protvar, servvar, uservar, passvar,
                            dirvar, filevar, remdirvar, fileglob)
                if protvar == "s3":
                    print(
                        f"Starting transfers to {y_}s3://{_nc}:{p_}{remdirvar}{_nc}: \n")
                    servvar, uservar, passvar = (" ", " ", " ")
                    s3Upload(dirvar, filevar, fileglob, remdirvar)


def mpfuDirUpload():
    # If serverlist file NOT supplied as CLI argument
    if not args.list:
        print(f"""

Serverlist not provided at CLI. Defaulting to {y_}single machine{_nc} directory upload mode.
If you wish to upload to multiple machines, provide a serverlist when running {bld_}MPFU{_nc}:
{y_}mpfu -l serverlist.txt{_nc}
        """)
        print(f"\nCurrently only {y_}SFTP{_nc} (and therefore Linux systems) are supported for this function.\n")
        servvar = servPrompt()
        uservar = input("\nUsername: ")
        passvar = ""
        
        term_width, term_height = os.get_terminal_size()
        try:
            pssh = paramiko.SSHClient()
            pssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            pssh.connect(hostname=servvar, username=uservar,
                         timeout=8)
            sftpc = pssh.open_sftp()

        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.SSHException):
            print(
               f"\n{y_}No SSH key matching this host to authenticate with.{_nc}\n\nEnter password for {y_}{uservar}{_nc}: ", end=" ")
            passvar = getpass.getpass('')

            pssh = paramiko.SSHClient()
            pssh.load_system_host_keys()
            pssh.set_missing_host_key_policy(paramiko.WarningPolicy())
            pssh.connect(hostname=servvar, username=uservar, password=passvar,
                        timeout=8)
            sftpc = pssh.open_sftp()
        
        remdirvar = input(
            "\nRemote directory on server to upload local directory (if nonexistent, it will be created): ")
        readline.set_completer(t.pathCompleter)
        dirvar = input("\nLocal directory to upload (include leading slash): ")
        print(" ")
        protvar = "SFTP"

        try:
            dirvar = dirvar.replace('\\', '/').rstrip("/")
            os.chdir(os.path.split(dirvar)[0])
            parent = os.path.split(dirvar)[1]
            dirnum = 0
            filenum = 0

            if plat_type == 'Linux':
                os.system('setterm -cursor off')
            for walker in os.walk(parent):
                try:
                    remdir_create = os.path.normpath(os.path.join(
                        remdirvar, walker[0])).replace('\\', '/')
                    pretty_remdir = (
                        remdir_create[:20] + "..." + remdir_create[-35:]) if len(remdir_create) > term_width - 15 else remdir_create
                    remdir_creation = f"Creating {p_}{pretty_remdir}{_nc}=>"
                    print(remdir_creation + " "
                          * (term_width - len(remdir_creation) - 1))
                    sftpc.mkdir(os.path.normpath(os.path.join(
                        remdirvar, walker[0])).replace('\\', '/'))
                    dirnum += 1
                except Exception as e:
                    print(f"{r_}Can't create dir{_nc} {p_}{pretty_remdir}{_nc}{r_}; already exists or bad permissions{_nc}")
                    print("")

                for file in walker[2]:
                    print(f"Transferring: {g_}{file}{_nc}", end="\r")
                    transferprog = f"Transferring: {g_}{file}{_nc}"
                    print(transferprog + " " * (term_width
                                                - len(transferprog) - 1), end="\r")
                    sftpc.put(os.path.normpath(os.path.join(walker[0], file)).replace(
                        '\\', '/'), os.path.join(remdirvar, walker[0], file).replace('\\', '/'))
                    filenum += 1

            if plat_type == 'Linux':
                os.system('setterm -cursor on')
            sftpc.close()
            print(f"Finished transferring {y_}{dirnum}{_nc} directories and {y_}{filenum}{_nc} files.")

        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.BadAuthenticationType):
            print(f"""
    {r_}<ERROR>
    Username, password, or SSH key are incorrect, or the server is not accepting the type of authentication attempted{_nc}.\n""")
            input("Press a key to continue...")
            print(" ")
            return
        except (BlockingIOError, socket.timeout):
            print(f"""
    {r_}<ERROR>
    Server is offline, unavailable, or otherwise not responding. Check the hostname or IP and try again.{_nc}\n""")
            input("Press a key to continue...")
            print(" ")
            return

    elif args.list:
        print(
            f"""
Currently only {y_}SFTP{_nc} (and therefore Linux systems) are supported for this function. Other protocols and
systems from the list will be ignored.""")
        
        remdirvar = input(
            "\nRemote directory on servers to upload local directory (if nonexistent, it will be created): ")
        readline.set_completer(t.pathCompleter)
        dirvar = input("\nLocal directory to upload (include leading slash): ")
        print(" ")
        term_width, term_height = os.get_terminal_size()

        with open(args.list, 'r') as serv_file:
            ufile_input = serv_file.read()
            sfile_input = ufile_input.strip()

            # Loop through input list and parse into variables
            split_input = sfile_input.split("\n")
            for e in range(len(split_input)):
                pop_input = split_input.pop()
                elem = pop_input.split(":")
                protvar = elem[0]
                if protvar == "sftp":
                    servvar = elem[1].strip()
                    uservar = elem[3].strip()
                    passvar = elem[4].strip()
                else:
                    continue
                try:
                    pssh = paramiko.SSHClient()
                    pssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    pssh.connect(hostname=servvar, username=uservar,
                                timeout=8)
                    sftpc = pssh.open_sftp()
                except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.SSHException):
                    print(
                        f"\n{r_}No SSH key matching this host to authenticate with.{_nc}\n")
                    print(f"Enter password for {y_}{uservar}{_nc}: ")

                    passvar = getpass.getpass('')

                    pssh = paramiko.SSHClient()
                    pssh.load_system_host_keys()
                    pssh.set_missing_host_key_policy(paramiko.WarningPolicy())
                    pssh.connect(hostname=servvar, username=uservar, password=passvar,
                                timeout=8)
                    sftpc = pssh.open_sftp()
                try:
                    print(f"\nStarting directory transfer to {b_}{servvar}{_nc}: ")
                    pssh = paramiko.SSHClient()
                    pssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    pssh.connect(hostname=servvar, username=uservar,
                                 password=passvar, timeout=8)
                    sftpc = pssh.open_sftp()

                    dirvar = dirvar.replace('\\', '/').rstrip("/")
                    os.chdir(os.path.split(dirvar)[0])
                    parent = os.path.split(dirvar)[1]
                    dirnum = 0
                    filenum = 0

                    if plat_type == 'Linux':
                        os.system('setterm -cursor off')
                    for walker in os.walk(parent):
                        try:
                            remdir_create = os.path.normpath(os.path.join(
                                remdirvar, walker[0])).replace('\\', '/')
                            pretty_remdir = (
                                remdir_create[:20] + "..." + remdir_create[-35:]) if len(remdir_create) > term_width - 15 else remdir_create
                            remdir_creation = f"Creating {p_}{pretty_remdir}{_nc}=>"
                            print(remdir_creation + " "
                                  * (term_width - len(remdir_creation) - 1))
                            sftpc.mkdir(os.path.normpath(os.path.join(
                                remdirvar, walker[0])).replace('\\', '/'))
                            dirnum += 1
                        except Exception as e:
                            print(f"{r_}Can't create dir{_nc} {p_}{pretty_remdir}{_nc}{r_}; already exists or bad permissions{_nc}")
                            print("")

                        for file in walker[2]:
                            print(f"Transferring: {g_}{file}{_nc}", end="\r")
                            transferprog = f"Transferring: {g_}{file}{_nc}"
                            print(transferprog + " " * (term_width
                                                        - len(transferprog) - 1), end="\r")
                            sftpc.put(os.path.normpath(os.path.join(walker[0], file)).replace(
                                '\\', '/'), os.path.join(remdirvar, walker[0], file).replace('\\', '/'))
                            filenum += 1
                    if plat_type == 'Linux':
                        os.system('setterm -cursor on')
                    sftpc.close()
                    print(f"Finished transferring {y_}{dirnum}{_nc} directories and {y_}{filenum}{_nc} files.")

                except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.BadAuthenticationType):
                    print(f"""
{r_}<ERROR>
Username, password, or SSH key are incorrect, or the server is not accepting the type of authentication attempted{_nc}.\n""")
                    input("Press a key to continue...")
                    print(" ")
                    return
                except (BlockingIOError, socket.timeout):
                    print(f"""
{r_}<ERROR>
Server is offline, unavailable, or otherwise not responding. Check the hostname or IP and try again.{_nc}\n""")
                    input("Press a key to continue...")
                    print(" ")
                    return
                except (Exception, IOError) as e:
                    print(f"""
{r_}<ERROR>
The server raised an exception: {e} {_nc}\n""")
                    input("Press a key to continue...")
                    print(" ")
                    return


def mpfuSSH():
    import fabric
    import fabric.exceptions

    # Load in previous connections for tab completion
    _, lastserv_f = lastServ()
    t.createListCompleter(lastserv_f)
    readline.set_completer(t.listCompleter)

    # Initialize list to buffer multiple cmd output for tab completion
    bufferlist = []

    # If serverlist file NOT supplied as CLI argument
    if not args.list:
        print(f"""
Serverlist not provided at CLI. Defaulting to {y_}single machine{_nc} control mode.
If you wish to issue commands to multiple machines, provide a serverlist when running {bld_}MPFU{_nc}:
{y_}mpfu -l serverlist.txt{_nc}
        """)
        try:
            connectloop = 1
            while connectloop == 1:

                login_prompt = f"\nEnter user and server for command ({y_}username@server.address.net{_nc}): "
                ssh_prompt = input(login_prompt).strip()
                uservar, servvar = ssh_prompt.split('@')[0], ssh_prompt.split('@')[1]
                conn = fabric.Connection(servvar, user=uservar)

                with open(os.path.join(homepath, 'sav.mpfu'), 'a') as lastserv_u:
                    lastserv_u.write('\n' + servvar)

                try:
                    conn.open()
                except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.SSHException):
                    print(
                        f"\n{y_}No SSH key matching this host to authenticate with.{_nc}\n\nEnter password for {y_}{uservar}{_nc}: ", end=" ")
                    passvar = getpass.getpass('')

                    passauth_conn = fabric.Connection(servvar, user=uservar, connect_kwargs={
                                                  "password": passvar})

                    passauth_conn.open()

                    passauthloop = 1
                    while passauthloop == 1:
                        print(f"\nConnecting to {b_}{servvar}{_nc} =>", end="")
                        cmdvar = input(
                            "\nEnter command to run on server (Ctrl-D to return to menu): ")
                        print(" ")
                        cmdresult = passauth_conn.run(cmdvar)

                        # Create list of cmd output lines, append them to buffer each cmd, and deduplicate
                        outputlist = [c for c in cmdresult.stdout.split("\n")]
                        bufferlist.extend(outputlist)
                        bufferset = set(bufferlist)

                        t.createListCompleter(bufferset)
                        readline.set_completer(t.listCompleter)

                        print(" ")
                except socket.gaierror as e:
                    print(f"{r_}The command returned an error{_nc}: {e}")
                    continue


                cmdloop = 1
                while cmdloop == 1:
                    try:
                        print(f"\nConnecting to {b_}{servvar}{_nc} =>", end="")
                        cmdvar = input(
                            "\nEnter command to run on server (Ctrl-D to return to menu): ")
                        print(" ")
                        cmdresult = conn.run(cmdvar)

                        # Create list of cmd output lines, append them to buffer each cmd, and deduplicate
                        outputlist = [c for c in cmdresult.stdout]
                        bufferlist.extend(outputlist)
                        bufferset = set(bufferlist)

                        t.createListCompleter(bufferset)
                        readline.set_completer(t.listCompleter)
                        print(" ")
                    except EOFError:
                        connectloop = 0
                        break
                    except Exception as e:
                        print(f"{r_}The command returned an error{_nc}: {e}\n")
        except EOFError:
            pass
    elif args.list:
        cmdvar = input(
            "\nEnter command to run on servers in list (Ctrl-D to return to menu): ")
        with open(args.list, 'r') as serv_file:
            ufile_input = serv_file.read()
            sfile_input = ufile_input.strip()

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
                    continue
                try:
                    print(f"\nConnecting to {b_}{servvar}{_nc} =>")
                    print(" ")
                    cmdresult = fabric.Connection(servvar, user=uservar, connect_kwargs={
                                                  "password": passvar}).run(cmdvar)
                    print(" ")
                    input("Press a key to continue (Ctrl-D to return to menu)...")
                except EOFError:
                    break
                except Exception as e:
                    print(f"{r_}The command returned an error{_nc}: {e}\n")
                    try:
                        input("Press a key to continue (Ctrl-D to return to menu)...")
                    except EOFError:
                        break
# MPFU menu function
def mpfuMenu():

    # Revert back to path completer after returning to menu
    bashCompleter()

    # Reset working dir to homepath
    os.chdir(homepath)
    print(f"""
            {bld_}__  __ ___ ___ _   _
           |  \/  | _ \ __| | | |
           | |\/| |  _/ _|| |_| |
           |_|  |_|_| |_|  \___/{_nc}""")
    print(f"""
     -=|Multi-Protocol File Uploader|=-

 {bld_}|Upload|{_nc}

 1) Upload local files to {y_}one{_nc} destination (server, share, bucket, etc.)
 2) Upload local files to {y_}multiple{_nc} destinations from manual INPUT
 3) Upload local files to {y_}multiple{_nc} destinations from a {y_}list{_nc} entered at CLI (mpfu -l serverlist.txt)
 4) Upload a {y_}directory{_nc} recursively (all subdirectories and files) to one or more destinations (SFTP only)\n

 {bld_}|Control|{_nc}

 S) Issue a {y_}command{_nc} over {y_}SSH{_nc} to one or more remote machines


 q) Quit\n""")

    choicevar = input(
        f"Select an option [{y_}CTRL-D at any time returns to main menu{_nc}]: ").strip()

    if choicevar == "1":
        mpfuUpload()
    elif choicevar == "2":
        mpfuMultiUpload()
    elif choicevar == "3":
        mpfuMultiUploadFile()
    elif choicevar == "4":
        mpfuDirUpload()
    elif choicevar == "s" or choicevar == "S":
        mpfuSSH()
    elif choicevar == "q" or choicevar == "Q":
        print("\n")
        sys.exit()
    else:
        print(f"\n{r_}Not an option!{_nc}")
metaloop = 1
while metaloop == 1:
    try:
        menuloop = 1
        while menuloop == 1:
            try:
                mpfuMenu()
            except EOFError:
                pass
    except Exception as e:
        print(f"{r_}An exception occurred: {e}{_nc}")
