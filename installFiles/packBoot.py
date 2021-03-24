#!/usr/bin/env python
''''packBoot -- unpack an Android boot.img to a kernel file and unpacked ramdisk --
repack the ramdisk directory back into a ramdisk and pack with kernel
@author: ribo
'''
import sys, os, time, subprocess, shutil, traceback
# In reviveMC74.py, packBoot.py is called from with the installFiles directory
# ribou.py is the cwd (parent of installFiles, add cwd to path
sys.path.append(os.getcwd())

from ribou import *
from datetime import datetime


def unpack(biFn):
  '''Unpack a boot image file
  '''
  try:
    fn, ext = biFn.split('.')
  except: fn = biFn
  unDir = fn+"Unpack"
  try:
    shutil.rmtree(unDir)
  except:
    pass  # Directory may exist
  os.mkdir(unDir)
  os.chdir(unDir)
  print("cwd "+os.getcwd())

  resp, rc = execute("unpackbootimg -i ../"+biFn)
  print("unpackbootimg "+biFn+": (rc="+str(rc)+") resp:\n"+prefix("  |", resp))
  if rc==1:
    print("  (This partition img was probably not a boot partition.)")
    os.chdir("..")  # Didn't unpack, back out and remove ..Unpack dir
    try:
      shutil.rmtree(unDir)
    except:
      pass  # Directory may exist
    return False

  # Remove the 'rmcBoot.imgRaw-' prefix from all the file names
  for ff in listDir('.', False):
    newFn = ff.split('-', 1)[1]
    shutil.move(ff, newFn)

  print("ls-unpack "+os.getcwd()+":\n"+prefix("--|", '\n'.join(listDir('.',
    False))))

  resp, rc = execute("gunzip ramdisk.gz")
  print("gunzip ramdisk.gz: "+str(rc)+"\n"+resp)
  rd = readFile("ramdisk", ascii=False)
  print("ramdisk "+str(len(rd))+" bytes")
  lsRdOrig, rc = execu("cpio -i -tv", rd)
  #writeFile("../"+fn+"LsRdOrig", lsRdOrig)
  #print(lsRdOrig)
  #import pdb; pdb.set_trace()

  os.chdir("..")
  rdDir = fn+"Ramdisk"
  try:
    shutil.rmtree(rdDir)
  except:
    pass
  os.mkdir(rdDir)
  os.chdir(rdDir)
  print("cwd rd "+os.getcwd())
  
  resp, rc = execu("cpio -i -m", rd)
    # -m is preservce file modification time
  print("cpio -i <ramdisk: "+str(rc)+"\n"+resp)
  

def pack(biFn):
  '''Pack a bootRamdisk dir back into a ramdisk, and build an image file
     from booUnpack dir
  '''
  print("pack: "+biFn)
  try:
    fn, ext = biFn.split('.')
  except: fn = biFn
  unDir = fn+"Unpack"
  rdDir = fn+"Ramdisk"

  # In bootRamdisk dir, recreate the cpio archive
  os.chdir(rdDir)
  print("  cwd rd "+os.getcwd())

  fl = listDir('.')
  fl.sort()   # Sort filenames alphabetically
  fList = ""
  for ff in fl:
    if len(ff)>2:  # Remove blank lines and './'
      fList += ff[2:]+"\n"
  
  pr(fList)

  outFid = "../"+unDir+"/ramdisk"
  rd, rc = execu("cpio -o -H newc -R 0.0 -F "+outFid, fList, showErr=False,
    returnStr=False)
  print("cpio -o  rc="+str(rc)+", "+str(os.path.getsize(outFid))+" bytes")


  # In the bootUnpack directory, write the ramdisk file and gzip it
  os.chdir("../"+unDir)
  print("ls-pack "+os.getcwd()+":\n"+prefix("--|", '\n'.join(listDir(os.getcwd(),
    False))))
  #try:
  #  os.remove("ramdisk")
  #except: pass
  #writeFile("ramdisk", rd)
  #lsRdNew, rc = execute("cpio -tv -I ramdisk")


  # Compress ramdisk
  try:
    os.remove("ramdisk.gz")
  except: pass
  resp, rc = execute("gzip ramdisk")
  print(" ramdisk gzipped "+str(rc))


  # Build file system image file
  cmdline = removeCRLF(readFile("cmdline"))
  base = removeCRLF(readFile("base"))
  pagesize = removeCRLF(readFile("pagesize"))
  ts = datetime.now().strftime("%y%m%d%H%M")
  cmd = ["mkbootimg", "--kernel", "zImage",
    "--ramdisk", "ramdisk.gz", "--cmdline", cmdline,
    "--base", "0x"+base, "--pagesize", pagesize, "--output", "../"+biFn+ts ]
  # Note: --cmdline contains spaces, we must pass the command as tokens so
  # execute() won't .split(' ') the command to prepare the args array
  print("cmd: '"+str(cmd)+"'")
  resp, rc = execute(cmd)
  print("(rc="+str(rc)+") resp:\n"+prefix("  |", resp))

  os.chdir("..")
  #writeFile(fn+"LsRdNew", lsRdNew)


def listDir(dir, recursive=True, search=''):
  # Replacement for 'find . -print' on Windows
  lst = []
  for fn in os.listdir(dir):
    subdir = dir+'/'+fn
    if search in subdir: 
      lst.append(subdir)
    if recursive and os.path.isdir(subdir):
      lst.extend(listDir(subdir))
  return lst


def removeCRLF(ln):  # Remove all trailing LFs and CRs
  while len(ln)>0 and ln[-1]=='\r' or ln[-1]=='\n':
    ln = ln[:-1]
  return ln


if __name__ == '__main__':
  try:
    # Set defaults (which may be changed by name=value arguments)
    op = 'unpack'

    if len(sys.argv)<2:
      print("packBoot needs arg 'pack' or 'unpack <filename>'")

    else:
      op = sys.argv[1]
      args = []
      argList = sys.argv[2:]  # Remove the program name and pack/unpack mode token
      for arg in argList:
        if '=' in arg:
          args.remove(arg)
          arg = arg.split('=')  # Handle name=val arguments
          locals()[arg[0]] = arg[1]  # Add name to locals
        else:
          args.append(arg)

      biFn = args[0] if len(args)>0 else "boot.img"
      if op == 'pack':
        pack(biFn)
      else:
        unpack(biFn)
  except Exception as ex:
    # (Do not use hndExcept, it reads from stdin, and would hang reviveMC74.py)
    print("packBoot exception: "+traceback.format_exc())
