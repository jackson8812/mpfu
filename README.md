# MPFU
Multi-Protocol File Uploader

MPFU is a cross-platform (Windows and Linux currently, macOS in the future?) and is capable of sending one or more files to multiple destination servers (from a text file or input manually) using different protocols for each connection, if desired. 

#### Features:
- **FTP, SFTP, SCP, SMB/CIFS, AWS S3 upload**
   - S3 upload requires a shared AWS credential file, config file, or environment variable. awscli installation is recommended.
- **One-to-one, one-to-many, or many-to-many uploads from manual input or a list in text format**
- **Windows and Linux support**
- **Tab completion for filesystem paths and filenames on all platforms**
- **Pretty(?) colors**

Python 3 is required for the script version.

A Windows EXE version is available in the EXE folder. It is standalone and does not require Python or anything else to be installed.
