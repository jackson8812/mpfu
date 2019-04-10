# MPFU :file_folder::rocket::cloud:
Multi-Protocol File Uploader

MPFU is a cross-platform (Windows and Linux currently, macOS in the future?) file upload utility and is capable of sending one or more files to multiple destination servers (from a text file or input manually) using different protocols for each connection, if desired. 

#### Features:
- **FTP, SFTP, SCP, SMB/CIFS, AWS S3 upload**
   - S3 upload requires a shared AWS credential file, config file, or environment variable. awscli installation is recommended.
- **One-to-one, one-to-many, or many-to-many uploads from manual input or a list in text format**
- **SSH remote command to one or more remote machines**
   - This feature is not meant to replace a normal SSH session, but rather to complement the upload feature. For instance, you can            upload an install or deployment script to multiple remote machines, then run the script on all the remote machines in sequence,            within the same MPFU session and using the same serverlist.
- **Windows and Linux support**
- **Tab completion for filesystem paths and filenames on all platforms**
- **Pretty(?) colors**

Python 3 is required for the script version.

In the /exe/ folder are a Windows EXE version, and a Linux ELF version. They are both standalone and do not require Python or anything else to be installed.
