# encoding: UTF-8
#
# PhotoFilmStrip - Creates movies out of your pictures.
#
# Copyright (C) 2011 Jens Goepfert
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
import os
import re
import threading
import queue
import io
from subprocess import Popen, PIPE, STDOUT

from photofilmstrip.core.Aspect import Aspect
from photofilmstrip.core.OutputProfile import OutputProfile
from photofilmstrip.core.BaseRenderer import BaseRenderer, RendererException


class ResultFeeder(threading.Thread):
    def __init__(self, renderer):
        threading.Thread.__init__(self, name="ResultFeeder")
        self.resQueue = queue.Queue(20)
        self.active = 1
        self.renderer = renderer
        
    def run(self):
        while 1:
            result = None
            try:
                result = self.resQueue.get(True, 1.0)
            except queue.Empty:
                if self.active:
                    continue
                else:
                    break

            logging.getLogger("ResultFeeder").debug("result queue size: %s; result size %s",
                                                    self.resQueue.qsize(), 
                                                    len(result))
            self.renderer.GetSink().write(result)


class _MEncoderRenderer(BaseRenderer):
    
    def __init__(self):
        BaseRenderer.__init__(self)
        
        self._encOut = None
        self._encErr = None
        
        self._procEncoder = None
        self._feeder = None
        
    @staticmethod
    def CheckDependencies(msgList):
        try:
            proc = Popen(["mencoder"], stdout=PIPE, stderr=STDOUT, shell=False)
            output = proc.communicate()[0]
        except Exception as err:
            logging.debug("checking for mencoder failed: %s", err)
            output = ""
        if not re.search("^(mplayer|mencoder)", output, re.I):
            msgList.append(_(u"mencoder (mencoder) required!"))

    @staticmethod
    def GetProperties():
        return ["Bitrate", "RenderSubtitle"]

    @staticmethod
    def GetDefaultProperty(prop):
        if prop == "RenderSubtitle":
            return "false"
        return BaseRenderer.GetDefaultProperty(prop)

    def ProcessFinalize(self, pilImg):
#        pilImg.save(self._procEncoder.stdin, 'JPEG', quality=95)
#        return
        res = io.StringIO()
        pilImg.save(res, 'JPEG', quality=95)
        self._feeder.resQueue.put(res.getvalue())
    
    def __CleanUp(self):
        if self._procEncoder is None:
            return
        
        self._feeder.active = 0
        self._feeder.join()
        
        self._procEncoder.communicate()

        for log in [self._encOut, self._encErr]:
            if log:
                log.close()
        self._procEncoder = None
        self._feeder = None
        
    def ProcessAbort(self):
        self.__CleanUp()

    def Prepare(self):
        self._encOut = open(os.path.join(self.GetOutputPath(), "mencoder_out.log"), 'w')
        self._encErr = open(os.path.join(self.GetOutputPath(), "mencoder_err.log"), 'w')
        
        cmd = self._GetCmd()
        self._procEncoder = Popen(cmd, stdin=PIPE, stdout=self._encOut, stderr=self._encErr, shell=False)#, bufsize=-1)
        
        self._feeder = ResultFeeder(self)
        self._feeder.start()
        
    def GetSink(self):
        return self._procEncoder.stdin
    
    def Finalize(self):
        self.__CleanUp()
        
        if not (self.__class__.GetProperty("RenderSubtitle").lower() in ["0", _(u"no"), "false"]):
            # delete subtitle file, if subtitle is rendered in video
            srtPath = os.path.join(self.GetOutputPath(), "output.srt")
            if os.path.exists(srtPath):
                os.remove(srtPath)

    def _GetCmd(self):
        raise NotImplementedError()
    
    def _GetSubArgs(self):
        if not (self.__class__.GetProperty("RenderSubtitle").lower() in ["0", _(u"no"), "false"]):
            subArgs = ["-sub", os.path.join(self.GetOutputPath(), "output.srt"),
                       "-subcp", "utf8"]
        else:
            subArgs = []
        return subArgs
    
    def _GetAudioArgs(self):
        if self.GetAudioFile() is None:
            audioArgs = []
        else:
            audioArgs = ["-audiofile", self.GetAudioFile()]
        return audioArgs
    
    def _GetFrameRate(self):
        if self.GetProfile().GetVideoNorm() == OutputProfile.PAL:
            framerate = "25/1"
        else:
            framerate = "30000/1001"
        return framerate
    
    def _GetBitrate(self):
        if self.__class__.GetProperty("Bitrate") == self.__class__.GetDefaultProperty("Bitrate"):
            bitrate = self.GetProfile().GetBitrate()
        else:
            try:
                bitrate = int(self.__class__.GetProperty("Bitrate"))
            except:
                raise RendererException(_(u"Bitrate must be a number!"))
        return bitrate


class _MPEGRenderer(_MEncoderRenderer):
    
    def __init__(self):
        _MEncoderRenderer.__init__(self)
        
    @staticmethod
    def GetProperties():
        return _MEncoderRenderer.GetProperties()

    @staticmethod
    def GetDefaultProperty(prop):
        return _MEncoderRenderer.GetDefaultProperty(prop)

    def _GetCmd(self):
        aspect = "%.3f" % Aspect.ToFloat(self._aspect)
        profile = self.GetProfile()
        if profile.GetVideoNorm() == OutputProfile.PAL:
            keyint = 15
#             res = profile.GetResolution()
        else:
            keyint = 18
#             res = profile.GetResolution()
            
        if profile.GetName() not in ["VCD", "SVCD", "DVD"]:
            raise RendererException(_(u'MPEG format supports only VCD, SVCD and DVD profile!'))

        srate, lavcopts = self._GetCmdOptions(aspect, keyint)
            
#              "-vf scale=%(resx)d:%(resy)d,harddup " \
#              "-of mpeg -mpegopts format=%(format)s " \
#              "-ofps %(framerate)s " \
        cmd = ["mencoder", "-demuxer", "lavf", "-fps", "25", "-lavfdopts", "format=mjpeg"]
        cmd += self._GetAudioArgs()
        cmd += self._GetSubArgs()
        cmd += ["-oac", "lavc", "-ovc", "lavc",
                "-of", "lavf", "-lavfopts", "format=mpg",
                "-srate", srate, "-af", "lavcresample=%s" % srate,
                "-lavcopts", lavcopts, 
                "-ofps", "25",
                "-o", os.path.join(self.GetOutputPath(), "output.mpg"),
                "-"]        
        return cmd
    
    def _GetCmdOptions(self, aspect, keyint):
        raise NotImplementedError()


class VCDFormat(_MPEGRenderer):
    
    @staticmethod
    def GetName():
        return "VCD (MPG)"
    
    def _GetCmdOptions(self, aspect, keyint):
#         mpgFormat = "xvcd"
        srate = "44100"
        lavcopts = "vcodec=mpeg1video:keyint=%(keyint)s:vrc_buf_size=327:vrc_minrate=1152:vbitrate=1152:vrc_maxrate=1152:acodec=mp2:abitrate=224:aspect=%(aspect)s" % {"keyint": keyint,
                                                                                                                                                                       "aspect": aspect}
        return srate, lavcopts


class SVCDFormat(_MPEGRenderer):
    
    @staticmethod
    def GetName():
        return "SVCD (MPG)"
    
    def _GetCmdOptions(self, aspect, keyint):
#         mpgFormat = "xsvcd"
        srate = "44100"
        lavcopts = "vcodec=mpeg2video:mbd=2:keyint=%(keyint)s:vrc_buf_size=917:vrc_minrate=600:vbitrate=2500:vrc_maxrate=2500:acodec=mp2:abitrate=224:aspect=%(aspect)s" % {"keyint": keyint,
                                                                                                                                                                            "aspect": aspect}
        return srate, lavcopts


class DVDFormat(_MPEGRenderer):
    
    @staticmethod
    def GetName():
        return "DVD (MPG)"
    
    def _GetCmdOptions(self, aspect, keyint):
#         mpgFormat = "dvd:tsaf"
        srate = "48000"
        lavcopts = "vcodec=mpeg2video:vrc_buf_size=1835:vrc_maxrate=9800:vbitrate=5000:keyint=%(keyint)s:vstrict=0:acodec=ac3:abitrate=192:aspect=%(aspect)s" % {"keyint": keyint,
                                                                                                                                                                 "aspect": aspect}
        return srate, lavcopts


class MPEG4AC3Renderer(_MEncoderRenderer):
    
    def __init__(self):
        _MEncoderRenderer.__init__(self)
        
    @staticmethod
    def GetName():
        return _(u"MPEG4-XVid/AC3 (AVI)")

    @staticmethod
    def GetProperties():
        return _MEncoderRenderer.GetProperties() + ["FFOURCC"]

    @staticmethod
    def GetDefaultProperty(prop):
        if prop == "FFOURCC":
            return "XVID"
        return _MEncoderRenderer.GetDefaultProperty(prop)

    def _GetCmd(self):
        cmd = ["mencoder", "-demuxer", "lavf", "-fps", "25", "-lavfdopts", "format=mjpeg"]
        cmd += self._GetAudioArgs()
        cmd += self._GetSubArgs()
        cmd += ["-oac", "lavc", "-srate", "44100",
                "-ovc", "lavc", 
                "-lavcopts", "vcodec=mpeg4:vbitrate=%d:vhq:autoaspect:acodec=ac3" % self._GetBitrate(), 
                "-ffourcc", MPEG4AC3Renderer.GetProperty('FFOURCC'),
                "-ofps", self._GetFrameRate(),
                "-o", os.path.join(self.GetOutputPath(), "output.avi"),
                "-"]
        return cmd


class _MEncoderMP3Renderer(_MEncoderRenderer):
    
    def __init__(self):
        _MEncoderRenderer.__init__(self)
        
    @staticmethod
    def CheckDependencies(msgList):
        _MEncoderRenderer.CheckDependencies(msgList)
        if msgList:
            return
        
        try:
            proc = Popen(["mencoder", "-oac", "help"], stdout=PIPE, stderr=STDOUT, shell=False)
            output = proc.communicate()[0]
        except Exception as err:
            logging.debug("checking for mencoder (mp3support) failed: %s", err)
            output = ""
        
        if output.find("mp3lame") == -1:
            msgList.append(_(u"mencoder with MP3 support (mp3lame) required!"))


class MPEG4MP3Renderer(_MEncoderMP3Renderer):
    
    def __init__(self):
        _MEncoderMP3Renderer.__init__(self)
        
    @staticmethod
    def GetName():
        return _(u"MPEG4-XVid/MP3 (AVI)")

    @staticmethod
    def GetProperties():
        return _MEncoderMP3Renderer.GetProperties() + ["FFOURCC"]

    @staticmethod
    def GetDefaultProperty(prop):
        if prop == "FFOURCC":
            return "XVID"
        return _MEncoderMP3Renderer.GetDefaultProperty(prop)

    def _GetCmd(self):
        cmd = ["mencoder", "-demuxer", "lavf", "-fps", "25", "-lavfdopts", "format=mjpeg"]
        cmd += self._GetAudioArgs()
        cmd += self._GetSubArgs()
        cmd += ["-oac", "mp3lame", "-lameopts", "cbr:br=192", "-srate", "44100",
                "-ovc", "lavc", 
                "-lavcopts", "vcodec=mpeg4:vbitrate=%d:vhq:autoaspect" % self._GetBitrate(), 
                "-ffourcc", MPEG4MP3Renderer.GetProperty('FFOURCC'),
                "-ofps", self._GetFrameRate(),
                "-o", os.path.join(self.GetOutputPath(), "output.avi"),
                "-"]
        return cmd


class FlashMovieRenderer(_MEncoderMP3Renderer):
    
    def __init__(self):
        _MEncoderMP3Renderer.__init__(self)
        
    @staticmethod
    def GetName():
        return _(u"Flash-Video (FLV)")
    
    def _GetCmd(self):
        cmd = ["mencoder", "-demuxer", "lavf", "-fps", "25", "-lavfdopts", "format=mjpeg"]
        cmd += self._GetAudioArgs()
        cmd += self._GetSubArgs()
        cmd += ["-oac", "mp3lame", "-lameopts", "cbr:br=128", "-srate", "44100",
                "-ovc", "lavc", 
                "-lavcopts", "vcodec=flv:vbitrate=%d:mbd=2:mv0:trell:v4mv:cbp:last_pred=3" % self._GetBitrate(),
                "-of", "lavf",
                "-ofps", self._GetFrameRate(),
                "-o", os.path.join(self.GetOutputPath(), "output.flv"),
                "-"]
        return cmd


class MJPEGRenderer(_MEncoderRenderer):
    
    def __init__(self):
        _MEncoderRenderer.__init__(self)
        
    @staticmethod
    def GetName():
        return _(u"Motion-JPEG (AVI)")
    
    def _GetCmd(self):
        cmd = ["mencoder", "-demuxer", "lavf", "-fps", "25", "-lavfdopts", "format=mjpeg"]
        cmd += self._GetAudioArgs()
        cmd += self._GetSubArgs()
        cmd += ["-oac", "pcm", "-srate", "44100",
                "-ovc", "lavc", 
                "-lavcopts", "vcodec=mjpeg",
                "-of", "lavf",
                "-ofps", self._GetFrameRate(),
                "-o", os.path.join(self.GetOutputPath(), "output.avi"),
                "-"]
        return cmd
