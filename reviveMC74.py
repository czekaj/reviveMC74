#!/usr/bin/env python
'''reviveMC74 -- Semiautomatic program to recover/revive/reflash a stock Meraki MC74,
  incrementally and restartably.

reviveMC74.py <options> <objectiveName>

Options:'''  # See options bunch below for list of options

helpTail = '''\nEach time reviveMC74 is called, it reassess the state conversion of the device
and resumes the update process from that point.  The first positional argument is the name of
the update objective to be done.  Use the objective 'listObjectives' to get a list of 
defined objectives.  The default objective is 'revive', which means unlock the MC74 by flashing 
a new recovery image, and patching the boot.img to run in not secure mode, uninstall
the Meraki apps and to install reviveMC74.apk
'''

# python reviveMC74.py installApps host=phCom

import sys, os, time, datetime, shutil
from ribou import *
from examImg import * # Utilities for reviveMC74

installFilesDir = "installFiles"
filesPresentFid = "filesPresent.flag"
  # If this file exists, we checked that needed files are here

neededProgs = bunch(  # These are commands that demonstrate that needed programs are in the
  # PATH and that they execute (ie not just the filename of the program
  adb = ["adb version", "adbNeeded"],   
  fastboot = ["fastboot", "adbNeeded"],
  unpackbootimg = ["unpackbootimg", "unpNeeded"],
  mkbootimg = ["mkbootimg", "unpNeeded"],
  chmod = ["chmod --version", "unpNeeded"],
  cpio = ["cpio --version", "unpNeeded"],
  gzip = ["gzip -V", "gzipNeeded"], 
  gunzip = ["gunzip -V", "gzipNeeded"], 
)

neededFiles = bunch(
  recoveryClockImg = "recovery-clockwork-touch-6.0.4.7-mc74v2.img",
  packBootPy = "packBoot.py"
)

installFiles = bunch(
  lights = ["lights", "/system/bin", "chmod 755"],
  sockSvr = ["sockSvr", "/system/bin", "chmod 755"],
  hex = ["hex", "/system/bin", "chmod 755"],
  pp = ["pp", "/system/bin", "chmod 755"]
)

installFilesExtra = bunch(
  EXTRAmc74local = ["MC74local.mp", "/ssm/store", "chmod 664"],
  EXTRAldb = ["ldb", "/system/bin", "chmod 755"],
  EXTRArelaunch = ["relaunch", "/system/bin", "chmod 755"]
)

installApps = bunch(
  launcher = ["com.teslacoilsw.launcher-4.1.0-41000-minAPI16.apk", "com.teslacoilsw.launcher"],
  ssm = ["revive.SSMService-debug.apk", "ribo.ssm"],
  reviveMC74 = ["revive.MC74-debug.apk", "revive.MC74"]
)

installAppsExtra = bunch(
  EXTRAdolphin = ["Dolphin-12.2.3.apk", "mobi.mgeek.TunnyBrowser"],
  EXTRAmagicEarth = ["com.generalmagic.magicearth_7.1.21.19.54A366E7.0648D6B8-2021051206_minAPI16(armeabi-v7a)(nodpi)_apkmirror.com.apk", "com.generalmagic.magicearth"],
  EXTRAvoiceRecorder = ["com.coffeebeanventures.easyvoicerecorder_2.4.1-11049_minAPI16(nodpi)_apkmirror.com.apk", "com.coffeebeanventures.easyvoicerecorder"]
)


options = bunch(
  #sendOid=[None, 'o:', 'Name of object to send as body of command'],
  #sessionMode = [False, 's', 'Loop reading commands from stdin'],
  extra = [False, 'x', 'Install extra apps/files'],  # Private, not for general use
  help = [False, '?', 'Print help info']
)

arg = bunch(  # Place to store args for objective funcs to use
  part = "both",  # Target partition to backup or fix/install, ie 'boot', 'both' or 'boot2'
)
sys.arg = arg  # Make it universal (not just global (to reviveMC74)) so examImg.executeAdb sees it
# Options:
#   part  -- specify which parition to read or write(flash) data to
#   img   -- full filename of disk image to write/flash in flashPart objective


def reviveMain(args):
  global target, arg, installFilesDir

  if type(args)==str:
    args = args.split(' ')
  while len(args)>0:
    if args[0][0]!='-':  # Is this an option?
      break;  # Not an option, remaining tokens are args
    tok = args.pop(0)[1:]  # Get the first token, remove the leading '-'
    while len(tok)>0:
      tokLen = len(tok)  # See if option is processed and option letter removed
      for nn, vv in options.items():
        if vv[1][0]==tok[0]:  # Does this option def match this option letter?
          if len(vv[1])>1 and vv[1][1]==':':  # Is an value token expected?
            # Set the value of this option (vv[0]) to the rest of tok,
            # or the next token
            vv[0] = tok[1:] if len(tok)>1 else args.pop(0)
            tok = ""  # Token has been consumed
          else:  # No value expected, just the option letter
            tok = tok[1:]  # Consume this option letter
            vv[0] = True
          break
      if len(tok) == tokLen:
        print("Unrecognized option letter '"+tok[0]+"', ('"+tok+"')")
        return

  if options.help[0]:  # If the -? option was given, display help info
    print(__doc__)
    for nn, vv in options.items():
      print("  -%s %s # %s" % (vv[1][0],
        nn.ljust(8) if len(vv[1])>1 and  vv[1][1]==':' else "        ", vv[2]))
    print(helpTail)
    return

  #print(""+str(len(args))+" args: '"+str(args)+"'")

  if len(args)==0:
    target = "revive"
  else:
    target = args.pop(0)  # Take first token (after the options) as final objective

  # Parse args, set them as variables in global 'arg' var
  for tok in args:
    tok = tok.split('=')
    arg[tok[0]] = tok[1] if len(tok)==2 else True
  
  if target=='listObjectives':
    listObjectivesFunc()
    return

  # Connect to the requested host if needed (device must be rooted/revived first)
  if 'host' in arg:
    resp, rc = executeAdb("shell getprop ro.serialno")
    if resp.find("error:") == 0:  # Resp probably: "error: device 'xxx:5555' not found\r\n"
      if arg.host.find(':') == -1: arg.host += ":5555"
      resp, rc = execute("adb connect "+arg.host)   # !Do not use executeAdb()
      logp("  connecting to "+arg.host+": "+resp)

  # Verify that the needed programs and files are/were present
  # if installedFilesDir is not local to the current directory, find it (only for developers)
  if os.path.isdir(installFilesDir) == False:  # Does installFilesDir exist here?
    uid = os.environ.get("SUDO_USER") 
    if uid == None: uid = os.environ.get("USER")
    if uid == None: uid = "dummy"  # uid is usually set for Linux
    installFilesDir = "/home/"+uid+"/git/reviveMC74/installFiles"
    if os.path.isdir(installFilesDir) == False:
      installFilesDir = "/git/reviveMC74/installFiles"
      if os.path.isdir(installFilesDir) == False:
        print("Can't find installation files dir")
        print("  Did you do: git clone https://github.com/reviveMC74/reviveMC74.git")
        return False

  if os.path.isfile(filesPresentFid) == False:
    if checkFilesFunc():
      writeFile(filesPresentFid, "ok")
    else:
      print("Not all needed programs are in the 'PATH' or not all files are"
        +" present in this directory:")
      for line in state.error:
        print("  --"+line)

      if "adbNeeded" in state.needed:
        print("\nADB/FASTBOOT programs needed.  See:\n"
          +"  https://www.xda-developers.com/install-adb-windows-macos-linux/\n"
          +"  for instructions.  If you have adb and fastboot, make sure they"
          +" are in the 'path'"
          +"\n  (For experts, see: reviveMC74.py  neededProgs.adb[0] for the"
          +" command we use to test.)"
        )
        
      if "unpNeeded" in state.needed:
        print("\nUNPACKBOOTIMG/MKBOOTIMG/CPIO/CHMOD programs needed.  To download, see:\n"
          +"  https://forum.xda-developers.com/showthread.php?t=2073775\n"
          +"  or: https://github.com/huaixzk/android_win_tool   for precompiled"
          +" windows version\n"
          +"  or: https://github.com/osm0sis/mkbootimg   for the source code.\n"
          +"  Make sure that 'unpackbootimg', 'mkbootimg', 'chmod' and 'cpio' are in"
          +" the 'path'."
        )
        
      if "gzipNeeded" in state.needed:
        print("\nGZIP/GUNZIP programs needed.  To for windows, see:\n"
          +"  https://sourceforge.net/projects/unxutils/files/unxutils/current/UnxUtils.zip/download"
          +"To get 'UnxUtil.zip.  From that file extract: 'usr/local/wbin/gunzip.exe' "
          +"and 'usr/local/wbin/gzip.exe' to a directory that is in your PATH." 
        )
        
      return

  # Execute the target objective's 'func', it will call it's prerequisites
  try:
    func = eval(target+"Func")
  except: 
    # Objective not found, show list of objectives
    listObjectivesFunc()
    return

  if type(func).__name__ != 'function':
    print("Can't find function for objective '"+target+"'")
    return

  print(target+" Function: "+' '.join(args))  
  log(target+' '.join(args)+"===================================================================", prefix="\n")
  if func():
    print("Acheived objective '"+target+"'")
  else:
    print(target+" failed:")
    for line in state.error:
      print("  --"+line)

  log(rformat(state))  # Log the state of the operation on completion



# VARIOUS UTILITY FUNCTIONS --------------------------------------------------
def chkProg(pg):
    progName = pg[0].split(' ')[0]
    
    # First, try using 'which'
    which_path = shutil.which(progName)
    if which_path:
        print(f"Found {progName} at: {which_path}")
        return True
    
    # If 'which' fails, try the original command
    try:
        resp, rc = execute(pg[0], False)
        print(f"Executed '{pg[0]}', return code: {rc}")
        if rc == 0:
            print(f"Successfully executed {progName}")
            return True
    except Exception as e:
        print(f"Error executing {progName}: {str(e)}")
    
    print(f"Failed to find or execute {progName}")
    state.error.append(f"checkProgs: Can't find '{progName}' program")
    state.needed.append(pg[1])
    return False


def chkFile(fid):
  if os.path.isfile(installFilesDir+"/"+fid):
    return True
  else:
    state.error.append("checkFiles: Can't find file '"+fid+"'")
    return False


# FUNCTIONS FOR CARRYING OUT OBJECTIVES ----------------------------------------
def reviveFunc():
  logp("--(reviveFunc)") 
  #if adbModeFunc("normal") == False:
  if flashPartFunc()==False:
    print("flashPartFunc failed")  
    return False

  if installAppsFunc()==False:
    print("installAppsFunc failed")  
    return False

  if startPhoneFunc()==False:
    print("startPhoneFunc failed")  
    return False
  return True


def replaceRecoveryFunc():
  ''' Use fastboot to flash the CWM recovery image, recoveryClock.img to the recovery 
  partition, then reboot into 'adb' mode with the new unrestricted recovery mode

  The CWM interface should show on the phone's display.
  '''

  if state.adbMode != 'adb':
    if adbModeFunc("adb")==False: 
      return False

  # Has the recovery partition already been replaced?
  isReplaced = False
  resp, rc = executeAdbLog("shell grep secure default.prop")
  
  if findLine(resp, "ro.secure=0"):
    # This phone already has had the recovery replaced (ie shell cmd worked)
    # ro.secure has already been changed to '0', boot partition already fixed
    pass

  elif findLine(resp, "failed: No such file"):
    # The recovery partition has not been replaced, do it now
    # Switch to fastboot mode
    if state.adbMode != 'fastboot':
      if adbModeFunc("fastboot")==False:

        print("\nFailed to get into 'fastboot' mode.\n")   
        if os.name=="nt":
          print('''Either this command prompt is not running as 'administrator',
          or you need to change the device driver for the 'fastboot device', see:
          https://github.com/reviveMC74/reviveMC74/blob/main/doc/fastbootDrivers.md''')
        else:
          print('''Please rerun this as superuser.  For some reason, the 'fastboot flash recovery...'
          command needs to be run as root.''')

        return False

    logp("--replaceRecovery partition")

    if state.serialNo == "no permissions":
      logp("You must be in superuser mode (root) on Linux to flash a partition in 'fastboot'")
      return False

    logp("  --Writng revovery partition image:  "+neededFiles.recoveryClockImg)
    resp, rc = executeLog("fastboot flash recovery "+installFilesDir+"/"+neededFiles.recoveryClockImg)
    # IF this hangs on Linux, the problem may be that 'fastboot devices'
    # returns 'no permissions  fastboot', meaning that the user needs to be root to write to 
    # the USB device.    Try doing the fastboot commands as root, ie with sudo?

    print('''
    The recovery partition has been updated; the MC74 is going to reboot now.

    --Hold the 'mute' button down.
    --Press enter on this computer.
    --When the cisco/meraki logo appears and the vibrator grunts, release the 'mute' button
    --(The ClockworkRecovery UI should appear on the display.  You need not do anything on
      that display.)

    ''')
    try: 
      resp = input()  # Wait for the user to hold mute down and press enter
    except: 
      pass

    print("    --Rebooting")
    resp, rc = executeLog("fastboot reboot")
    bootWaitLoop("adb")  # Wait for reboot to finish before letting backupPartFunc continue

  state.replaceRecovery = True
  return True


def backupPartFunc():
  '''Backup a disk partition from the MC74, defaults to the 'boot' partition.  If it is
  the boot or boot2 partition, it is then unpacked into the rmcBoot[2]Unpack and the
  ramdisk from that boot image is unpacked into the rmcBoot[2]Ramdisk directory.
  For boot[2] paritiions, the backuped up img is named rmcBoot[2].imgRaw.  (
  fixPartFunc will produce the rmcBoot[2].img file from the .imgRaw.)  The first time
  backupPart backups up boot[2], it creates an rmcBoot[2].imgOrig copy of the .imgRaw.
  Other partitions are backedup to rmcXXXX.img.
  '''

  if replaceRecoveryFunc()==False:
    return False

  # Verify that the adb connection is in root mode
  resp, rc = executeAdbLog("shell id")
  if resp.find("(root)")==-1:
    logp("!! MC74 adbd is not in 'root' mode, can't continue")
    return False

  partName = arg.part  # Get name of partition to backup, defaults to 'boot'
  if partName=="both":
    partName = "boot"
  partFid = "/dev/block/platform/sdhci.1/by-name/"+partName
  if 'img' in arg:
    imgFn = arg.img
    makeOrig = False
  else:
    imgFn = 'rmc'+partName[:1].upper()+partName[1:]+".img"
    makeOrig = True
  if partName[:4]=='boot':
    imgFn += "Raw"  # Backing up boot produces .imgRaw, fixPartFunc uses this to create .img

  logp("backupPart "+partName+" partition: "+partFid)
  resp, rc = executeAdbLog("shell dd if="+partFid+" of=/cache/"+imgFn+" ibs=4096")
  resp, rc = executeAdb("pull /cache/"+imgFn+" .")
  resp, rc = executeAdbLog("shell rm /cache/"+imgFn)

  if os.path.isfile(imgFn)==False:
    logp("!!Can't find "+imgFn+" after pulling it")
    return False

  if partName[:4]!='boot':  # For non boot partitions we are done, success
    return True

  biSize = os.path.getsize(imgFn)
  if biSize!=8192*1024: 
    print("--"+imgFn+" file size is "+str(biSize)+", should be 8388608")
    return False
    
  print("  --unpack "+imgFn+" and unpack the ramdisk")
  resp, rc = executeLog(sys.executable+' '+installFilesDir+"/packBoot.py unpack "+imgFn)
  # sys.executable is the name of the python interpreter we are running

  if os.path.isfile(imgFn[:-3]+"Orig")==False:  # If no .imgOrig file, make it now
    # We should never overwrite this copy, the original copy from the phone
    # Subsequent explicit calls to backup and fix and flash boot partitions will operate
    # on an .imgRaw copy
    shutil.copy(imgFn, imgFn[:-3]+"Orig")

  return True


def fixPartFunc():
  ''' Edit default.prop file (and perhaps other) from rmcBootRamdisk directory, then pack the 
      ramdisk back into a rmcBoot.img file
  '''
  partName = arg.part  # Get name of partition to backup, defaults to 'boot'
  if partName=="both":
    partName = "boot"
  imgId = 'rmc'+partName[:1].upper()+partName[1:]
  rawFid = imgId+".imgRaw" if partName=="boot" else imgId+".img"
  rawImgExists = os.path.isfile(rawFid)

  if rawImgExists==False:
    if backupPartFunc()==False:
      return False

  if partName[:4]!="boot":  # Only the boot[2] partition needs to be 'fixed'
    return True

  if target!="fixPart" and os.path.isfile(imgId+".img")==True:
    print("  --skipping fixPart for "+imgId+".img partition, already done")
    return True  # For normal revive, if boot is fixed, skip it
    # If this is an explicit request to fixPart, do it

  logp("fixPartFunc "+imgId+".imgRaw to make it rooted.")
  try:
    os.remove(imgId+'.img')
  except:  pass

  # Edit default.props, change 'ro.secure=1' to 'ro.secure=0'
  # and: persist.meraki.usb_debug=0 to ...=1
  logp("  -- edit default.prop to change ro.secure to = 0")
  try:
    fn = imgId+"Ramdisk/default.prop"
    prop = readFile(fn)
    log("  default.prop:\n"+prefix('__', prop))

    try:
      ii = prop.index('secure=')+7
      prop = prop[:ii]+'0'+prop[ii+1:] # Change '1' to '0'
    except:  print("  --failed to find/replace 'secure=1'")
    try:
      ii = prop.index('usb_debug=')+10
      prop = prop[:ii]+'1'+prop[ii+1:] # Change '0' to '1'
    except:  print("  --failed to find/replace 'secure=1'")
    #log("itermediate default.prop:\n"++prefix('--', prop))

    # Remove \r from \r\n on windows systems
    pp = []
    for ln in prop.split('\n'):
      if ln[-1:]=='\r':  ln = ln[:-1]
      if len(ln)>0:
        #print("      .."+ln)
        pp.append(ln)
    writeFile(imgId+"Ramdisk/default.prop", '\n'.join(pp))
    # /default.prop will be ignored by system/core/init/init.c if writable by
    # group/other
    resp, rc = executeLog("chmod go-w "+imgId+"Ramdisk/default.prop")
    log("    fixed "+partName+" default.prop:\n"+prefix('__', '\n'.join(pp)))
  except IOError as err:
    logp("  !! Can't find: "+fn+" in "+os.getcwd()+"\n  !! Rerun the 'fixPart' objective.")
    return False

  # Add symlink to /ssm
  # in /init.rc after 'symlink /system/etc /etc' insert symlink /storage/emulated/legacy/ssm /ssm
  # in init.bcm911130_me1.rc after symlink.../sdcard  symlink /storage/emulated/legacy/ssm /ssm2
  editFile(imgId+"Ramdisk/init.rc", "symlink /system/etc",
    insert="    symlink /storage/emulated/legacy/ssm /ssm")

  logp("  -- repack ramdisk, repack "+imgId+".img")
  resp, rc = executeLog(sys.executable+' '+installFilesDir+"/packBoot.py pack "+imgId+".img")
  # sys.executable is the name of the python interpreter we are running
  #logp(prefix("  __|", '\n'.join(listDir(os.getcwd(), False, 'rmcBoot.img'))))
  if os.path.isfile(imgId+".img"):  # Make sure no .img file, we will rename
    hndExcept()
  

  # Rename the new file, rmcBoot.img2xxxxxxxxxxx (2... is the first digit in decade timestamp)
  for fid in os.listdir('.'):
    if fid[:len(imgId)+5] == imgId+'.img2':
      os.rename(fid, imgId+'.img')
      break
  log(prefix("  ..|", '\n'.join(listDir(os.getcwd(), False, 'rmcBoot.img'))))

  if os.path.isfile(imgId+".img"):  # Did packBoot succeed in creating .img file?
    return True
  else:
    state.error.append("fixPart: Can't find file '"+imgId+".img' after packBoot returned.")
    return False


def flashPartFunc():
  '''Write a parition image to the device then copy it to the specified partition
  By default this 'flashes' 'rmcBoot.img' to the 'boot' partition, but by
  specifiying 'part=???' and/or 'img=???' options, any image can be written
  to any partition.
  ''' 
  doBoth = False
  partName = arg.part  # Get name of partition to backup, defaults to 'boot'
  if partName == "both":
    partName = "boot"
    doBoth = True
  partFid = "/dev/block/platform/sdhci.1/by-name/"+partName
  if 'img' in arg:
    imgFn = arg.img
  else:
    imgFn = 'rmc'+partName[:1].upper()+partName[1:]+".img"

  # If flashPart was not explicitly called, test to see if it has been done
  if target != "flashPart":
    # Check timestamp of rmcBoot.img with copy stored in /data/boot.versionDate
    if os.path.isfile(imgFn):
      imgDt, imgTm, imgSz = fileDtTm(imgFn)  # Get timestamp of the local boot.img
      print("    local "+imgFn+" timestamp: "+imgDt+' '+imgTm+' '+str(imgSz))
      resp, rc = executeAdbLog("shell mount /data")
      resp, rc = executeAdb("pull /data/"+partName+".versionDate .")
      try:
        vDate = readFile(partName+".versionDate").split(' ')
        instDt, instTm, instSz = vDate[:3]
        print("    remote "+partName+".versionDate timestamp: "+instDt+' '+instTm+' '+str(instSz))

        if imgDt==instDt and imgTm==instTm:
          logp("    ("+imgFn+" timestamp matches installed versionDate, skipping flash of "
            +partName+")")
          return True
      except:
        pass  # parname.versionDate file won't exist before recovery was installed, okay.
    else:
      pass  # rmcBoot.img doesn't exist, backupPar and fixPart etc need to be run...

  # If the partition image file doesn't exist, run the fixPartFunc
  if os.path.isfile(imgFn)==False and partName[:4]=='boot':
    logp("    ("+imgFn+" not found, calling fixPart to create it)")
    if fixPartFunc()==False:
      return False

  logp("  flashPartFunc, writing "+imgFn+" to "+partFid)
  resp, rc = executeAdbLog("push "+imgFn+" /cache/"+imgFn)
  if rc!=0:
    state.error.append("Writing "+imgFn+" on device failed")
    return False

  resp, rc = executeAdbLog("shell dd if=/cache/"+imgFn+" of="+partFid
    +" ibs=4096")
  if rc!=0:
    state.error.append("Copying "+imgFn+" on device, to "+partName+" failed")
    return False
  if doBoth:
    resp, rc = executeAdbLog("shell dd if=/cache/"+imgFn+" of="+partFid+'2'
      +" ibs=4096")
    if rc!=0:
      state.error.append("Copying "+imgFn+" on device, to "+partName+"2 failed")
      return False

  resp, rc = executeAdbLog("shell rm /cache/"+imgFn)

  # Record timestamp and size of partition image file to allow for flashPart
  # verification above
  partDate = fileDtTm(imgFn) 
  try:
    md5 = execute('md5 '+imgFn)[0].split()[0][:8]  # record part of the md5sum of the file
  except:
    md5 = "(noMD5)"
  partDate = partDate[0]+' '+partDate[1]+' '+str(partDate[2])+' '+imgFn+" "+md5
  resp, rc = executeAdbLog("shell mount /data")
  print("mount /data: %d %s" % (rc, resp))
  resp, rc = executeAdbLog("shell echo "+partDate+" > /data/"+partName+".versionDate")
  print("echo versiobDate: %d %s" % (rc, resp))
  resp, rc = executeAdbLog("shell cat /data/"+partName+".versionDate")
  print("versionDate readback: %d %s" % (rc, resp))
  # Cause adbd to be started (as root) when it boots in normal mode
  resp, rc = executeAdbLog("shell echo -n 1 >/data/property/persist.meraki.usb_debug")
  logp("setting perist.meraki.usb_debug: %d %s" % (rc, resp))
  resp, rc = executeAdbLog("shell sync")
  resp, rc = executeAdbLog("shell umount /data")

  return True
  

def installAppsFunc():
  if adbModeFunc("normal")==False:  # Get into normal operation
    return False

  # TTD:  change telsacoilsw launcher DB
  if options.extra[0]:  # Was the -e option specified 
    # Add the extra files and apps to the install lists
    installFiles.update(installFilesExtra)
    installApps.update(installAppsExtra)

  logp("installAppsFunc, uninstall dialer2, droidNode, droidNodeSystemSvc, if not already done")

  # Uninstall apps.  Ignore errors where the file to remove is already not there.
  resp, rc = executeAdbLog("shell rm /system/app/DroidNode.apk", ignore="No such file")
  resp, rc = executeAdbLog("shell rm /system/app/DroidNodeSystemSvcs.apk",
    ignore="No such file")
  resp, rc = executeAdbLog("uninstall ribo.audtest", ignore="Failure")
  resp, rc = executeAdbLog("uninstall package:com.meraki.dialer2", ignore="Failure")
  resp, rc = executeAdbLog("shell rm /data/app/com.meraki.dialer2-2.apk",
    ignore="No such file")

  # Install programs
  for id in installFiles:
    print("  --install file/program: "+id)
    instFl = installFiles[id]
    isExtra = id[0:5] == "EXTRA"
    dir = installFilesDir
    if isExtra:  # If this is an extra file, read it from the .../extra dir
      dir += "/extra"
    resp, rc = executeAdbLog("push "+dir+"/"+instFl[0]+" "+instFl[1]+'/'+instFl[0]) 
    if len(instFl)>2:  # If there is a fixup cmd, do it (usually chmod)
      resp, rc = executeAdbLog("shell "+instFl[2]+" "+instFl[1]+'/'+instFl[0])

  # Replace click with sockSvr to disable Mtunnel, first save a backup
  resp, rc = executeAdb("shell ls /system/bin/clickOrig")
  if resp.find("No such file")>0:
    resp, rc = executeAdbLog("shell mv /system/bin/click /system/bin/clickOrig")
  resp, rc = executeAdbLog("shell ln -s /system/bin/sockSvr /system/bin/click",
    ignore="File exists")

  # Install/update new apps
  for id in installApps:
    fid = installApps[id][0]
    appTag = installApps[id][1]

    isExtra = id[0:5] == "EXTRA"
    dir = installFilesDir
    if isExtra:  # If this is an extra file, read it from the .../extra dir
      dir += "/extra"

    newDt, newTm, newSz = fileDtTm(dir+"/"+fid)

    # If app is already installed see if we have a newer version
    doInstall = True
    instDt, instTm, instSz = remoteFileDtTm("/data/app/"+appTag+"*", appTag)
    if instDt != None:
      logp("    installed copy of "+id+":   "+instDt+" "+instTm+"  size: "+str(instSz))
      # Is the installed apk, instDt the same or new?
      if newDt<=instDt and newSz==instSz:
        logp("    (Installed version of "+id+" is good, skipping install. (new "
          +newDt+' '+str(newSz)+")")
        doInstall = False
     
    if doInstall:
      logp("  --installing app: "+id+"     ("+newDt+' '+newTm+' '+str(newSz)+")")
      resp, rc = executeAdbLog("install -t -r "+dir+"/"+fid)
  

  # Make the shell prompt something short, edit file is used by /system/etc/mkshrc
  resp, rc = executeAdb("shell rm /sdcard/SHELL_PROMPT")
  resp, rc = executeAdb("shell touch /sdcard/SHELL_PROMPT")


  if options.extra[0]:  # Do extra install stuff (not for general users)
    print("(do extra install ops)")
    # Set .linphonerc reg_expire, register refresh interval to 10 min


  # Change Nova Launcher favorites db to make Phone connect to reviveMC74, add icons
  initLauncher()


  # Record the eth0 mac address
  # 'ip addr | grep \ eth0:' look like:
  # 3: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP qlen 512
  #     link/ether e0:55:3d:50:56:10 brd ff:ff:ff:ff:ff:ff
  resp, rc = executeAdb("shell ip addr |grep -A1 eth0: | grep ether")
  state.mac = resp.strip().split(' ')[1]
  print("  (mac "+state.mac+")");
  
  state.installApps = True
  return True


def checkFilesFunc():
  succeeded = True 

  for id in neededProgs:
    succeeded &= chkProg(neededProgs[id]) # Execute cmds to verify programs installed

  for id in neededFiles:
    succeeded &= chkFile(neededFiles[id]) # Verify files exist in installFiles dir

  for id in installFiles:
    succeeded &= chkFile(installFiles[id][0]) # (Programs/Files to be installed)

  for id in installApps:
    succeeded &= chkFile(installApps[id][0]) # (Apps are also in installFiles dir)

  state.checkFiles = succeeded
  return succeeded
 

def adbModeFunc(targetMode="adb"):
  '''Instruct user how to get MC74 in adb mode.
  
  Note: The factory recovery mode does not have the 'sh' command available, therefore
  adb functionality is limited.
  '''
  isAdb = False
  isFastboot = False
  isNormal = False  # Normal is: booted into normal dev operation, not recovery mode
  
 
  # Figure out what mode we are currently in
  currentMode = "unknown"
  resp, rc = executeLog("adb devices")
  if findLine(resp, "\trecovery"):
    currentMode = "recovery"
    isAdb = True
  if findLine(resp, "\tdevice"):
    currentMode = "normal"
    isNormal = True
    isAdb = True  # Normal mode (after fixing) should also adb enabled.
  else:
    resp, rc = executeLog("fastboot devices")
    ln = findLine(resp, "\tfastboot")
    if ln:
      currentMode = "fastboot"
      state.serialNo = ln.split('\t')[0]
      # Note: state.serialNo may be 'no permissions' if in Linux and not root!
      if targetMode=="fastboot":  # We are in fastboot, and that is the target mode
        state.adbMode = "fastboot"
        return True
      isFastboot = True
  
  logp("  --adbModeFunc, currentMode: "+currentMode+", targetMode: "+targetMode
    +(" adb" if isAdb else "")+(" normal" if isNormal else "")
    +(" fastboot" if isFastboot else ""))
  
  if currentMode == targetMode:
    pass  # Nothing to change
  
  elif isAdb and targetMode=="fastboot":
    print("    --Changing from adb mode to fastboot mode")
    resp, rc = executeLog("adb reboot bootloader")
  
  elif isAdb and targetMode=="adb":
    currentMode = targetMode  # normal mode should be eqivalent to adb after fixing
  
  elif targetMode=="adb" or targetMode=="recovery":
    # Reboot the MC74 into Recovery mode
    print('''
    Prepare to reboot the MC74.
      -- Remove the USB cable from the side of the MC74 (if connected)
      -- Remove the Ethernet/POE cable from the back of the MC74
      -- Reconnect the USB cable to the right side(not back) connector of the MC74
        (and the other end to the development computer)
    
    Now...
      -- Apply power with POE ethernet cable to WAN port (the ethernet port closest to the round
        socket on the back of the MC74.)
      -- quickly, press and hold mute button, before backlight flashes
      -- keep mute button down until cisco/meraki logo appears and vibrator grunts.
      -- release mute
      -- Press enter on the computer keyboard.
      -- (in about 15 sec, Windows should make the  'usb device attached' sound.)
    ''')
    try:
      resp = input()
    except:
      pass
    
  elif isNormal==False and targetMode=="normal":
    print("    --Changing from "+currentMode+" mode to normal device mode")
    if isFastboot:
      resp, rc = executeLog("fastboot reboot")
      
    else:
      #resp, rc = executeLog("adb reboot")  --This seems to hang in clockwork recovery mode
      # Per https://opensource.com/article/19/7/reboot-linux  reboot can be forced with:
      #   echo b > /proc/sysrq-trigger
      # (if /proc/sys/kernel/sysrq is set to '1', which seems to be the case in clockwork recovery)
      resp, rc = executeLog(['adb', 'shell', "echo b >/proc/sysrq-trigger"])
      log("reboot by sysrq, rc="+str(rc)+": "+resp)
    
  else:
    print("adbMode request to go from '"+currentMode+"' mode to '"+targetMode+"'.")
    print("  Don't know how to change to that mode.")
    return False
    
  if currentMode!=targetMode:
    return bootWaitLoop(targetMode)  # Loop waiting for the MC74 to finish booting
    
  state.adbMode = targetMode
  return True


def bootWaitLoop(tMode):
  '''Loop for a while waiting for the MC74 to finish booting into fastboot or adb mode
  '''
  cmd = "fastboot" if tMode=="fastboot" else "adb"
  print("  --loop running '"+cmd+" devices' until we see a device")
  searchStr = "\trecovery" if tMode=='adb' else "\tfastboot"
  if tMode == "normal":   searchStr = "\tdevice"

  for ii in range(0, 12):
    resp, rc = executeLog(cmd+" devices")
    ln = findLine(resp, searchStr)
    if ln:
      state.serialNo = ln.split('\t')[0]
      print("      found device with serial number: "+state.serialNo)
      state.adbMode = tMode
      return True

    print("--Waiting for reboot "+str(12-ii)+"/12: "+resp.replace('\n', ' '))
    time.sleep(5)
  state.adbMode = "unknown"
  return False


def resetBFFFunc():
  logp("resetBFFFunc")
  if os.path.isfile(filesPresentFid):
    os.remove(filePresentFid)
    print("The filesPresent.flag file was removed, next time you run"
      +" reviveMC74, it will recheck that you have all the needed files"
      +" and programs.")
  else:
    print("(There was no 'filesPresent.flag file.)")
  return True


def startPhoneFunc():
  logp("startPhoneFunc")
  resp, rc = executeAdbLog("shell am startservice ribo.ssm/.SSMservice")
  resp, rc = executeAdbLog("shell am start revive.MC74/org.linphone.dialer.DialerActivity")
  resp, rc = executeAdbLog("shell am force-stop com.meraki.droidnode")
  resp, rc = executeAdbLog("shell am force-stop com.meraki.dialer2")
  resp, rc = executeAdbLog("shell am force-stop com.meraki.dialer2:pjsip")

  msg = ""
  if "serialNo" in state: msg = "sn "+state.serialNo
  if "mac" in state: msg += "  mac "+state.mac
  if len(msg) > 0:
    print("  ("+msg+")");
  return True


def manualFunc():
  logp("\n Enter python commands on console...  (Ignore stuff about 'hndExcept' and 'exception')\n")
  try:
    hndExcept()
    return True
  except: hndExcept()


def versionFunc():
  logp("versionFunc --Gathers information about the software version on the MC74")
  if state.adbMode != 'adb':
    if adbModeFunc("adb")==False: 
      print("Sorry, the MC74 needs to have ADB working in recovery or normal "
        +"device mode to work.")
      return False

  if state.adbMode == "recovery":
    # Mount /system, and /data  if in recovery mode
    resp, rc = executeAdbLog("shell mount /dev/block/platform/sdhci.1/by-name/system /system")
    resp, rc = executeAdbLog("shell mount /dev/block/platform/sdhci.1/by-name/userdata /data")
  
  iList = []

  # Get the device serial number from u-boot-env partition
  resp, rc = executeAdbLog("shell dd if=/dev/block/platform/sdhci.1/by-name/u-boot-env " \
    "of=/cache/uBootEnv bs=640 count=1")
  if rc==0:
    resp, rc = executeAdbLog("pull /cache/uBootEnv uBootEnv.tmp")
    resp, rc = executeAdbLog("shell rm /cache/uBootEnv")
    ube = readFile("uBootEnv.tmp")
    if len(ube)>5:  # Remove mysterious leading 5 bytes
      ube = ube[5:]

    for ii in reversed(range(0, len(ube))):  # Remove trail nulls from u-boot-env file
      if ube[ii]!='\0':
        ube = ube[:ii+1]
        break

    ube = ube.split('\0')
    log("u-boot-env:\n"+rformat(ube))
    for ln in ube:
      if len(ln)>3 and ln[:3]=='sn=':
        iList.append("devSN:\t"+ln[3:])
    try:
      os.remove("uBootEnv.tmp")
    except:  pass


  # Get ro.build.version.release, ro.build.id, ro.build.date
  propNames = ["ro.build.id", "ro.build.version.release", "ro.build.date"]
  resp, rc = executeAdb("shell cat /system/build.prop")
  prop = bunch()
  if rc == 0:
    lines = linesToList(resp)
    for ln in lines:
      nameVal = ln.split('=')  
      if len(nameVal)>1:  # If line doesn't contain an '=', it may be a comment
        prop[nameVal[0].strip()] = nameVal[1].strip()
  
  for pn in propNames:
    if pn in prop:
      iList.append(pn+":\t"+prop[pn])
    
  # Get date and size of various interesting files
  getDateTime(iList, "/init")
  getDateTime(iList, "/system/build.prop")
  getDateTime(iList, "/system/framework/am.jar")
  getDateTime(iList, "/cache/downloads/update.tar.gz")
  getDateTime(iList, "/cache/downloads/images/boot.img")
  getDateTime(iList, "/cache/downloads/images/system.img")

  # Read /proc/version (in normal mode)
  resp, rc = executeAdbLog("shell cat /proc/version")
  if rc==0:
    iList.append("/procVersion:\t"+resp)
  else:
    iList.append("/procVersion:\t(unknown, in recovery mode)")

  infoStr = ""
  for ln in iList:
    infoStr += "  "+ln+"\n"
  print("\nVersion Info:\n"+infoStr)
  writeFile("version.info", infoStr)
  return True


def pushFunc():
  '''Update the GIT reviveMC74 repository with the latest code.  This is not for use by 
  general users.'''

  # ssmJarAndr.bat
  # Copy SSM objects to SSM asset/store
  updateObjs = ['ANDRCONFIG', 'WEATHER', 'VOIP', 'VOIPSETTINGS', 'LOGPANEL', 'SMSPANEL' ] 
  for oid in updateObjs:
    shutil.copy2("/ssm/store/"+oid+".nob", "/andrStud/SSMservice/app/src/main/assets/store")
    # Note: copy2 preserves/copies the contents and file date and permissions etc

  # Change 'freshDate' in SSMservice.java
  dt = datetime.datetime.now().strftime("%y/%m/%d")
  newFD = '  public static String freshDate = "'+dt+'-00:00:00";'
  editFile('/andrStud/SSMservice/app/src/main/java/ribo/ssm/SSMservice.java', find="String freshDate =",
    replace=newFD)

  # Rebuild SSMservice and reviveMC74 .apks
  print("Rebuild the SSMservice and reviveMC74 .apks; then press enter.")
  try: 
    resp = input()  # Wait for user to rebuild .apks
  except: 
    pass

  os.chdir("/git/reviveMC74")
  updateFiles = [
    '/andrStud/SSMservice/app/build/outputs/apk/debug/revive.SSMService-debug.apk',
    '/git/MC74/app/build/outputs/apk/debug/revive.MC74-debug.apk',
    '/andrStud/hex/app/.cxx/cmake/debug/armeabi-v7a/hex',
    '/andrStud/hex/app/.cxx/cmake/debug/armeabi-v7a/lights',
    '/andrStud/hex/app/.cxx/cmake/debug/armeabi-v7a/sockSvr',
    '/andrStud/hex/app/.cxx/cmake/debug/armeabi-v7a/sendevent'
  ]
  for fid in updateFiles:
    shutil.copy2(fid, "installFiles")

  resp, rc = execute('git status')
  print(resp)
  print("\nUse git add to add any new files to repo?, then press enter")
  try: 
    resp = input()  # Let user do any git adds needed
    import pdb; pdb.set_trace()
    print("Enter commit message text:")
    commitMsg = input()  # Let user do any git adds needed
  except: 
    hndExcept()

  resp, rc = execute('git commit -am "'+commitMsg+'"')
  print("Execute: git push")


def listObjectivesFunc():
  print("\nList of objectives (phases or operations needed for revival) Case sensitive:")
  for ob in objectives:
    objName = ob[0]
    desc = ob[1]
    if desc[0]!='!':
      print("  "+objName+"\t"+desc)
  print("\n\nThe objectives are listed in the order they are normally preformed.\n")


state = bunch( # Attributes are added here to indicate state or progress in objective
  adbMode = None,
  error = [],   # A place to return a list of errors
  needed = []   # A list of messages that need to be displayed
)

# Collection of all defined objectives
#  Note: If 'func' attribute is missing, the function is:  <objectiveName>Func
objectives = [
  ['listObjectives', "(optional) Lists all objectives"],
  ['checkFiles', "Verifies that you have the needed files, apps, images, and programs."],
  ['adbMode', "Gets device into 'adb' mode, or 'fastboot' or 'normal' operation."],
  ['replaceRecovery', "Replace the recovery partition with a full featured recovery program"], 
  ['backupPart', "Backs up boot (or other specified partition)."],
  ['fixPart', "Changes default.prop file on the ramdisk to allow rooting."],
  ['flashPart', "Rewrites the (boot) partition image "],
  ['installApps', "Install VOIP phone app, uninstall old Meraki phone apps"],
  ['revive', "<--Install reviveMC74 apps --this is the principal objective--"],
  ['version', "Find and record some software version info"],
  ['manual', "Place to manually invoke reviveMC74 functions (advanced users)"],
  ['resetBFF', "(manual step) Reset the 'Boot partion Fixed Flag'"],
  ['push', '(for developers only) Update the local repo then push changes to github'],
] # end of objectives




if __name__ == "__main__":
  try:
    reviveMain(sys.argv[1:])
  except Exception as xx:
    import traceback
    logp("reviveMC74 exception: "+rformat(xx))
    tb = sys.exc_info()[2]
    st = traceback.extract_tb(tb)
    logp(prefix("  |", rformat(st)))
    hndExcept()
