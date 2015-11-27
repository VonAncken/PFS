# encoding: UTF-8
#
# PhotoFilmStrip - Creates movies out of your pictures.
#
# Copyright (C) 2010 Jens Goepfert
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

import logging
import re
import sys

from subprocess import Popen, PIPE

from photofilmstrip.lib.util import Encode


class MPlayer(object):
    
    def __init__(self, filename):
        self.filename = Encode(filename, sys.getfilesystemencoding())
        self.__proc = None
        self.__length = None
        
        self.__Identify()

    def __Identify(self):
        cmd = ["mplayer", "-identify", "-frames", "0", "-ao", "null", "-vo", "null", self.filename]
        try:
            proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=False)
            output = proc.communicate()[0]
        except Exception as err:
            logging.debug("identify audio with mplayer failed: %s", err)
            output = ""
        
        reo = re.compile(".*ID_LENGTH=(\d+)[.](\d+)*", re.DOTALL | re.MULTILINE)
        match = reo.match(output)
            
        try:
            if match is not None:
                self.__length = float(match.group(1))
        except:
            pass
#            import traceback
#            traceback.print_exc()
        
    def IsOk(self):
        return self.__length is not None
    
    def IsPlaying(self):
        return self.__proc is not None
    
    def Play(self):
        if self.__proc is None:
            cmd = ["mplayer", self.filename]
            try:
                self.__proc = Popen(cmd, stdin=PIPE, stderr=PIPE, stdout=PIPE, shell=False)
            except Exception as err:
                logging.debug("playing audio with mplayer failed: %s", err)
                self.__proc = None
    
    def Stop(self):
        self.Close()
    
    def Close(self):
        if self.__proc is not None:
            if sys.platform == "win32":
                self.__proc.terminate()
#                import ctypes
#                PROCESS_TERMINATE = 1
#                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, self.__proc.pid)
#                ctypes.windll.kernel32.TerminateProcess(handle, -1)
#                ctypes.windll.kernel32.CloseHandle(handle)
            else:
                self.__proc.communicate("q")
            self.__proc = None
    
    def GetLength(self):
        return self.__length
