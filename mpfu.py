#!/usr/bin/env python3
import os, sys, platform, getpass, glob, ftplib, paramiko, scp, warnings, urllib
from smb.SMBHandler import SMBHandler

# Detect platform
platform = platform.system()

# Platform specific imports
if platform == 'Linux':
    import readline
if platform == 'Windows':
    import colorama
    colorama.init()
    from pyreadline import Readline
    readline = Readline()

# Color tags
if platform == 'Linux':
    b_ = '\033[94m'
if platform == 'Windows':
    b_ = '\033[95m'
g_ = '\033[92m'
r_ = '\033[91m'
y_ = '\033[1;33m'
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

# if platform == 'Linux':
if __name__=="__main__":
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
    message = "\r    Size: "+str(total_bytes)+" bytes("\
              +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
    message += " || Amount of file transfered: [{0}] {1}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
    if transfered_bytes == total_bytes:
        message = "\r    Size: "+str(total_bytes)+" bytes("\
                  +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
        message += " || File transfered. [{0}] {1}%                    \r"\
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
    message = "\r    Size: "+str(total_bytes)+" bytes("\
              +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
    message += " || Amount of file transfered: [{0}] {1}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
    if fbar_bytes >= total_bytes:
        message = "\r    Size: "+str(total_bytes)+" bytes("\
                  +str(round(float(total_bytes)/pow(2, 20),2))+" MB)"
        message += " || File transfered. [{0}] {1}%                    \r"\
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
    message = "\r    Size: "+str(total_bytes)+" bytes("\
              +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
    message += " || Amount of file transfered: [{}] {}%\r".format(hashes + spaces,
                                                                    round(percent * 100, 2))
    if transfered_bytes == total_bytes:
        message = "\r    Size: "+str(total_bytes)+" bytes("\
                  +str(round(float(total_bytes)/pow(2, 20), 2))+" MB)"
        message += " || File transfered. [{}] {}%                    \r"\
                   .format(hashes + spaces, round(percent * 100, 2))
    sys.stdout.write(message)
    sys.stdout.flush()

# Protocol prompt function
def protPrompt():
    global protvar
    # Get connection and file path details
    print("""
    Choose connection protocol:

    1) FTP
    2) SFTP
    3) SCP
    4) CIFS/SMB (Windows File Share)""")

    protvar = input("\nEnter protocol [name or 1-3]: ")

    if protvar == "1":
        protvar = "ftp"
    elif protvar == "2":
        protvar = "sftp"
    elif protvar == "3":
        protvar = "scp"
    elif protvar == "4":
        protvar = "smb"

    # Warn about FTP security, SMB risk
    if protvar == "ftp":
        print("\nNote: {}FTP{} protocol is inherently {}insecure{}, your password will be encrypted, but file(s) are sent unencrypted!\n".format(y_,_nc,r_,_nc))
    elif protvar == "smb":
        print("\n{}!!!WARNING!!!{} This utility will overwrite any file on the share with same name as the uploaded file. {}USE CAUTION!{}".format(r_,_nc,y_,_nc))

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
def finalUpload(protvar,servvar,uservar,passvar,filevar,dirvar,remdirvar):

    # Pull path list into a glob for parsing
    fileglob = glob.glob(dirvar + filevar)

    if protvar == "ftp":
        session = ftplib.FTP_TLS()
        session.connect(servvar, 21)
        session.sendcmd('USER {}'.format(uservar))
        session.sendcmd('PASS {}'.format(passvar))
        if platform == 'Linux':
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
            print("Sending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,servvar,_nc,r_,remdirvar,_nc,y_,protvar.upper(),_nc))
            session.storbinary('STOR ' + gfile, file,callback=fbar)
            print("\n\n")
            file.close()
        session.quit()
        if platform == 'Linux':
            os.system('setterm -cursor on')

    if protvar == "sftp":
        pssh = paramiko.SSHClient()
        pssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        pssh.connect(hostname=servvar,username=uservar,password=passvar)
        sftpc = pssh.open_sftp()
        if platform == 'Linux':
            os.system('setterm -cursor off')
        for g in fileglob:
            if os.path.isdir(g):
                continue
            gfile = str(os.path.basename(g))
            print("Sending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,servvar,_nc,r_,remdirvar,_nc,y_,protvar.upper(),_nc))
            sftpc.put(g,remdirvar + gfile,callback=pbar)
            print("\n\n")
        sftpc.close()
        if platform == 'Linux':
            os.system('setterm -cursor on')

    if protvar == "scp":
        pssh = paramiko.SSHClient()
        pssh.load_system_host_keys()
        pssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        pssh.connect(hostname=servvar,username=uservar,password=passvar)
        pscp = scp.SCPClient(pssh.get_transport(), progress=sbar)
        if platform == 'Linux':
            os.system('setterm -cursor off')
        for g in fileglob:
            if os.path.isdir(g):
                continue
            gfile = str(os.path.basename(g))
            print("Sending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,servvar,_nc,r_,remdirvar,_nc,y_,protvar.upper(),_nc))
            pscp.put(g, remote_path=remdirvar)
            print("\n\n")
        pscp.close()
        if platform == 'Linux':
            os.system('setterm -cursor on')

    if protvar == "smb":
        smbhandle = urllib.request.build_opener(SMBHandler)
        for g in fileglob:
            if os.path.isdir(g):
                continue
            gfile = str(os.path.basename(g))
            file = open(g, 'rb')
            print("\nSending {}{}{} to {}{}{}:{}{}{} over {}{}{} =>".format(g_,g,_nc,b_,servvar,_nc,r_,remdirvar,_nc,y_,protvar.upper(),_nc))
            sizedisplay = "    Size: "+str(os.path.getsize(g))+" bytes("+str(round(float(os.path.getsize(g))/pow(2, 20), 2))+" MB) ||"
            print(sizedisplay)
            u = smbhandle.open('smb://{}:{}@{}{}{}'.format(uservar,passvar,servvar,remdirvar,gfile), data = file)
            print("\n")
            file.close()

# Single destination upload function
def mpfuUpload():
    # Pull in last connected server variable, prompt for current server, update sav.mpfu with current server
    global lastserv
    print("\nServer IP or hostname (Leave blank for last connected: [{}{}{}]): ".format(b_,lastserv,_nc), end = "")
    servvar = input()
    if servvar == "":
        servvar = lastserv
    lastserv_u = open('sav.mpfu', 'w')
    lastserv_u.write(servvar)
    lastserv_u.close()

    protPrompt()

    uservar = input("\nUsername: ")

    passvar = getpass.getpass("\nPassword: ")

    if protvar == "sftp":
        remdirvar = input("\nRemote upload directory (remote dir MUST be specified AND include leading and trailing slash): ")
    elif protvar == "smb":
        print("\nRemote upload share (input name of share with forward slashes, i.e. {}/network/share/{}): ".format(r_,_nc), end="")
        remdirvar = input()
    else:
        remdirvar = input("\nRemote upload directory (include leading and trailing slash, or leave blank for default): ")

    # If local directory NOT supplied as CLI argument
    # if len(sys.argv) == 1:
    dirvar = input("\nLocal directory containing files to upload (include leading slash): ")
    print("\nContents of directory: \n")
    # Filter subdirectories out of directory contents
    dirvarlist = os.listdir(dirvar)
    for file in dirvarlist:
        dirvaritem = os.path.join(dirvar, file)
        if os.path.isdir(dirvaritem):
            dirvarlist.remove(file)
    dirlist = '\n'.join(map(str,dirvarlist))
    print(dirlist)

    # Feed directory contents list into tab completer, if Linux
    if platform == 'Linux':
        t.createListCompleter(dirvarlist)
        readline.set_completer(t.listCompleter)
    filevar = input("\nFile(s) to upload (wildcards accepted): ")

    finalUpload(protvar,servvar,uservar,passvar,filevar,dirvar,remdirvar)

# MPFU multi-file upload function
def mpfuMultiUpload():
    print("""

You can upload one or more local files to a list of remote servers.
Please input the list in the following format. You can list several destinations separated by commas,
and with all elements separated by colons:

{}protocol{}:{}IP or hostname{}:{}/remotepath/{}:{}login{}:{}password{}

Enter server list in the format above:""".format(g_,_nc,b_,_nc,r_,_nc,y_,_nc,y_,_nc))
    inputlistvar = input("> ")

    protPrompt()

    # Prompt for local directory and list contents for file selection
    dirvar = input("\nLocal directory containing files to upload (include leading slash): ")
    print("\nContents of directory: \n")
    # Filter subdirectories out of directory contents
    dirvarlist = os.listdir(dirvar)
    for file in dirvarlist:
        dirvaritem = os.path.join(dirvar, file)
        if os.path.isdir(dirvaritem):
            dirvarlist.remove(file)
    dirvarlist = '\n'.join(map(str,dirvarlist))
    print(dirvarlist)

    # Feed directory contents list into tab completer
    if platform == 'Linux':
        t.createListCompleter(dirvarlist)
        readline.set_completer(t.listCompleter)
    filevar = input("\nFile(s) to upload (wildcards accepted): ")
    print("\n")

    # Loop through input list and parse into variables
    split_input = inputlistvar.split(",")
    for e in range(len(split_input)):
        pop_input = split_input.pop()
        elem = pop_input.split(":")
        servvar = elem[0]
        remdirvar = elem[1]
        uservar = elem[2]
        passvar = elem[3]

        # Perform uploads
        print("Starting transfers to {}{}{}: ".format(b_,servvar,_nc))
        finalUpload(protvar,servvar,uservar,passvar,filevar,dirvar,remdirvar)

# MPFU multi-file upload to destination list file
def mpfuMultiUploadFile():
    # If serverlist file NOT supplied as CLI argument
    if len(sys.argv) == 1:
        print("\n{}No server list file provided{}. Please run the script with the server list text file provided as an argument: {}./mpfu.sh{} {}serverlist{}".format(r_,_nc,b_,_nc,y_,_nc))
        print("""
Server list file must be text in the following format, one entry per line:

        {}protocol{}:{}IP or hostname{}:{}/remotepath/{}:{}login{}:{}password{}
        """.format(g_,_nc,b_,_nc,r_,_nc,y_,_nc,y_,_nc))
        quit()
    elif len(sys.argv) == 2:
        with open(sys.argv[1], 'r') as serv_file:
            ufile_input = serv_file.read()
            sfile_input = ufile_input.strip()

            # protPrompt()

            # Prompt for local directory and list contents for file selection
            dirvar = input("\nLocal directory containing files to upload (include leading slash): ")
            print("\nContents of directory: \n")
            # Filter subdirectories out of directory contents
            dirvarlist = os.listdir(dirvar)
            for file in dirvarlist:
                dirvaritem = os.path.join(dirvar, file)
                if os.path.isdir(dirvaritem):
                    dirvarlist.remove(file)
            dirvarlist = '\n'.join(map(str,dirvarlist))
            print(dirvarlist)

            # Feed directory contents list into tab completer
            if platform == 'Linux':
                t.createListCompleter(dirvarlist)
                readline.set_completer(t.listCompleter)
            filevar = input("\nFile(s) to upload (wildcards accepted): ")
            print("\n")
            # Loop through input list and parse into variables
            split_input = sfile_input.split("\n")
            for e in range(len(split_input)):
                pop_input = split_input.pop()
                elem = pop_input.split(":")
                protvar = elem[0]
                servvar = elem[1]
                remdirvar = elem[2]
                uservar = elem[3]
                passvar = elem[4]

                # Perform uploads
                print("Starting transfers to {}{}{}: ".format(b_,servvar,_nc))
                finalUpload(protvar,servvar,uservar,passvar,filevar,dirvar,remdirvar)

# MPFU menu function
def mpfuMenu():
    print("""
	 __  __ _____  ______ _    _
	|  \\/  |  __ \\|  ____| |  | |
	| \\  / | |__) | |__  | |  | |
	| |\\/| |  ___/|  __| | |  | |
	| |  | | |    | |    | |__| |
	|_|  |_|_|    |_|     \\____/""")
    print("""
     -=|Multi-Protocol File Uploader|=-

 |Upload|

 1) Upload local files to ONE destination server
 2) Upload local files to MULTIPLE destination servers from manual INPUT
 3) Upload local files to MULTIPLE destination servers from a LIST entered at CLI (./mpfu.py <filename>)\n\n""")

    choicevar = input("Select an option [1-3]: ")

    if choicevar == "1":
        mpfuUpload()
    elif choicevar == "2":
        mpfuMultiUpload()
    elif choicevar == "3":
        mpfuMultiUploadFile()
    else:
        print("\n{}Not an option!{}".format(r_,_nc))
        mpfuMenu()


mpfuMenu()
