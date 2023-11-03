# Copyright (c) 2019 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import sgtk
import os
import sys
import nuke
from datetime import datetime

from tank_vendor import six

HookBaseClass = sgtk.get_hook_baseclass()

ffmpeg_path = "V:/Scripts/FFMPEG/FFMPEG_Current/bin/ffmpeg.exe"

class RenderMedia(HookBaseClass):
    """
    RenderMedia hook implementation for the tk-nuke engine.
    """

    def __init__(self, *args, **kwargs):
        super(RenderMedia, self).__init__(*args, **kwargs)

        self.__app = self.parent

        self._burnin_nk = os.path.join(
            self.__app.disk_location, "resources", "occludeburns.nk"
        )
        self._font = os.path.join(
            self.__app.disk_location, "resources", "liberationsans_regular.ttf"
        )

        # If the slate_logo supplied was an empty string, the result of getting
        # the setting will be the config folder which is invalid so catch that
        # and make our logo path an empty string which Nuke won't have issues with.
        self._logo = None
        if os.path.isfile(self.__app.get_setting("slate_logo", "")):
            self._logo = self.__app.get_setting("slate_logo", "")
        else:
            self._logo = ""

        # now transform paths to be forward slashes, otherwise it wont work on windows.
        if sgtk.util.is_windows():
            self._font = self._font.replace(os.sep, "/")
            self._logo = self._logo.replace(os.sep, "/")
            self._burnin_nk = self._burnin_nk.replace(os.sep, "/")

    def render(
        self,
        input_path,
        output_path,
        width,
        height,
        first_frame,
        last_frame,
        version,
        name,
        color_space,
    ):
        """
        Use Nuke to render a movie.

        :param str input_path:      Path to the input frames for the movie
        :param str output_path:     Path to the output movie that will be rendered
        :param int width:           Width of the output movie
        :param int height:          Height of the output movie
        :param int first_frame:     The first frame of the sequence of frames.
        :param int last_frame:      The last frame of the sequence of frames.
        :param str version:         Version number to use for the output movie slate and burn-in
        :param str name:            Name to use in the slate for the output movie
        :param str color_space:     Colorspace of the input frames

        :returns:               Location of the rendered media
        :rtype:                 str
        """
        output_node = None
        ctx = self.__app.context

        # create group where everything happens
        group = nuke.nodes.Group()

        # now operate inside this group
        group.begin()
        try:
            # create read node
            read = nuke.nodes.Read(name="source", file=input_path.replace(os.sep, "/"))
            read["on_error"].setValue("black")
            read["first"].setValue(first_frame)
            read["last"].setValue(last_frame)
            if color_space:
                read["colorspace"].setValue(color_space)

            data = self.wrangleData(first_frame, last_frame)

            ''' Add shot LUT '''
            cubeFile = self.findCubeFile(ctx)
            if cubeFile is None:
                lut = self.createLUT_Node(read, None)
            else:
                lut = self.createLUT_Node(read, cubeFile)

            ''' Scale here to keep aspect to crop to format '''
            # create a scale node
            crop = False
            if crop:
                scale = self.__create_scale_node(width, height)
                scale.setInput(0, read if cubeFile is None else lut)

            # now create the slate/burnin node
            burn = nuke.nodePaste(self._burnin_nk)
            if cubeFile is None:
                burn.setInput(0, scale if crop else read)
            else:
                burn.setInput(1, scale if crop else lut)

            # add the logo
            burn.node("logo")["file"].setValue(self._logo)

            # format the burnins
            version_padding_format = "%%0%dd" % self.__app.get_setting(
                "version_number_padding"
            )
            version_str = version_padding_format % version

            if ctx.task:
                version_label = "%s, v%s" % (ctx.task["name"], version_str)
            elif ctx.step:
                version_label = "%s, v%s" % (ctx.step["name"], version_str)
            else:
                version_label = "v%s" % version_str

            ### INFO
            current_user = sgtk.util.get_current_user(self.__app.sgtk)
            filename = os.path.splitext(os.path.basename(input_path))[0]

            comment = self.retrieveComment(ctx, input_path,)

            ### BURN INS
            burn.node('top_left')['message'].setValue(ctx.project['name'])
            burn.node('top')['message'].setValue('')
            burn.node('top_right')['message'].setValue(datetime.today().strftime('%m/%d/%y'))
            burn.node('bottom_left')['message'].setValue('v{}'.format(version_str))
            burn.node('bottom')['message'].setValue(ctx.entity['name'])

            # and the slate
            burn.node('Project_Name')['message'].setValue(str(ctx.project['name']))
            burn.node('Date')['message'].setValue(datetime.today().strftime('%m/%d/%y'))
            burn.node('Filename')['message'].setValue(filename.split('.')[0])
            burn.node('Frames')['message'].setValue("{} - {}".format(first_frame, last_frame))
            burn.node('Artist')['message'].setValue(current_user['name'])
            burn.node('Version')['message'].setValue(version_label)
            burn.node('Notes')['message'].setValue(comment)


            # create a scale node
            scale = self.__create_scale_node(width, height)
            scale.setInput(0, burn)

            # Create the output node
            output_node = self.__create_output_node(output_path)
            output_node.setInput(0, scale)
        finally:
            group.end()

        if output_node:
            # Make sure the output folder exists
            output_folder = os.path.dirname(output_path)
            self.__app.ensure_folder_exists(output_folder)

            # Render the outputs, first view only
            nuke.executeMultiple(
                [output_node], ([first_frame - 1, last_frame, 1],), [nuke.views()[0]]
            )

        # Cleanup after ourselves
        nuke.delete(group)
        
        self.TranscodeFile(output_path, data)

        return output_path

    def __create_scale_node(self, width, height):
        """
        Create the Nuke scale node to resize the content.

        :param int width:           Width of the output movie
        :param int height:          Height of the output movie

        :returns:               Pre-configured Reformat node
        :rtype:                 Nuke node
        """
        scale = nuke.nodes.Reformat()
        scale["type"].setValue("to box")
        scale["box_width"].setValue(width)
        scale["box_height"].setValue(height)
        scale["resize"].setValue("fit")
        scale["box_fixed"].setValue(True)
        scale["center"].setValue(True)
        scale["black_outside"].setValue(True)
        return scale

    def __create_output_node(self, path):
        """
        Create the Nuke output node for the movie.

        :param str path:           Path of the output movie

        :returns:               Pre-configured Write node
        :rtype:                 Nuke node
        """
        # get the Write node settings we'll use for generating the Quicktime
        wn_settings = self.__get_quicktime_settings()

        node = nuke.nodes.Write(file_type=wn_settings.get("file_type"))

        # apply any additional knob settings provided by the hook. Now that the knob has been
        # created, we can be sure specific file_type settings will be valid.
        for knob_name, knob_value in six.iteritems(wn_settings):
            if knob_name != "file_type":
                node.knob(knob_name).setValue(knob_value)

        # Don't fail if we're in proxy mode. The default Nuke publish will fail if
        # you try and publish while in proxy mode. But in earlier versions of
        # tk-multi-publish (< v0.6.9) if there is no proxy template set, it falls
        # back on the full-res version and will succeed. This handles that case
        # and any custom cases where you may want to send your proxy render to
        # screening room.
        root_node = nuke.root()
        is_proxy = root_node["proxy"].value()
        if is_proxy:
            self.__app.log_info("Proxy mode is ON. Rendering proxy.")
            node["proxy"].setValue(path.replace(os.sep, "/"))
        else:
            node["file"].setValue(path.replace(os.sep, "/"))

        return node

    def __get_quicktime_settings(self, **kwargs):
        """
        Allows modifying default codec settings for Quicktime generation.
        Returns a dictionary of settings to be used for the Write Node that generates
        the Quicktime in Nuke.

        :returns:               Codec settings
        :rtype:                 dict
        """
        settings = {}
        if sgtk.util.is_windows() or sgtk.util.is_macos():
            settings["file_type"] = "mov"
            if nuke.NUKE_VERSION_MAJOR >= 9:
                # Nuke 9.0v1 changed the codec knob name to meta_codec and added an encoder knob
                # (which defaults to the new mov64 encoder/decoder).
                settings["meta_codec"] = "apcn"
            else:
                settings["codec"] = "jpeg"

        elif sgtk.util.is_linux():
            if nuke.NUKE_VERSION_MAJOR >= 9:
                # Nuke 9.0v1 removed ffmpeg and replaced it with the mov64 writer
                # http://help.thefoundry.co.uk/nuke/9.0/#appendices/appendixc/supported_file_formats.html
                settings["file_type"] = "mov64"
                settings["mov64_codec"] = "jpeg"
                settings["mov64_quality_max"] = "3"
            else:
                # the 'codec' knob name was changed to 'format' in Nuke 7.0
                settings["file_type"] = "ffmpeg"
                settings["format"] = "MOV format (mov)"

        return settings


    def createLUT_Node(self, read, path, colorspace='sRGB'):
        group = nuke.nodes.Group()
        group.begin()

        input = nuke.nodes.Input()
        
        if path != None:
            ft = nuke.nodes.OCIOFileTransform()
            ft['file'].setValue(path)
            ft['working_space'].setValue('sRGB')
            ft.setInput(0, input)
        else:
            ft = nuke.nodes.Colorspace()
            ft['colorspace_out'].setValue('sRGB')
            ft.setInput(0, input)

        cs = nuke.nodes.Colorspace()
        cs['colorspace_in'].setValue('sRGB')
        cs.setInput(0, ft)

        output = nuke.nodes.Output()
        output.setInput(0, cs)
        group.end()

        group.setInput(0, read)
        return group


    def wrangleData(self, ff, lf):
        frames = int(lf-ff+1)
        interval = int(frames/50)
        if interval == 0:
            numframes = frames
        else:
            numframes = int(frames/interval)
        thumb = int(frames/2)
        data = {
            'frames': frames,
            'fps': nuke.root()['fps'].getValue(),
            'interval': interval,
            'num_frames': numframes,
            'thumb': thumb,
                }

        return data


    def createMP4(self, fps, input, version):
        start = datetime.now()
        # vcodec = "libx264 -pix_fmt yuv422p10le \
        #           -g 30 -b:v 2000k -preset veryslow -bf 0 -movflags +faststart -crf 15 -tune film"
        vcodec = "libx264 -pix_fmt yuv420p \
                  -g 30 -b:v 2000k -preset veryslow -bf 0 -movflags +faststart -crf 17 -tune zerolatency"


        newfile = os.path.basename(input).replace('.mov', '.mp4')
        output =  os.path.join(version, newfile)

        args = " \
            -r {fps} \
            -i {input} \
            -vcodec {vcodec} \
            -acodec acc \
            {output}".format(
                fps=fps,
                input=input,
                vcodec=vcodec,
                output=output,
                    )

        os.system('cmd /c "{exe} -y -loglevel warning -stats {args}"'.format(
            exe=ffmpeg_path,
            args=args,
                )
            )
        elapsed = datetime.now() - start
        print('==> MP4 created! [{}]'.format(elapsed))
        return output


    def createWebM(self, fps, input, version):
        start = datetime.now()
        vcodec = "libvpx-vp9 -pix_fmt yuv420p -b:v 0 -crf 17 -threads 2 -speed 2"
        newfile = os.path.basename(input).replace('.mov', '.webm')
        output = os.path.join(version, newfile)

        args = " \
            -r {fps} \
            -i {input} \
            -vcodec {vcodec} \
            -acodec acc \
            {output}".format(
                fps=fps,
                input=input,
                vcodec=vcodec,
                output=output,
                    )

        os.system('cmd /c "{exe} -y -loglevel warning -stats {args}"'.format(
            exe=ffmpeg_path,
            args=args,
                )
            )
        elapsed = datetime.now() - start
        print('==> WebM created! [{}]'.format(elapsed))
        return output


    def createThumbnail(self, fps, file, thumb, version):
        start = datetime.now()
        output=os.path.join(version, os.path.basename(file).replace('.mov', '_thumbnail.jpg'))

        args = " \
            -r {fps} \
            -i {input} \
            -frames 1 \
            -vf \"scale=640:-1,select=gte(n\,{thumb})\" \
            {output} \
                ".format(
                    fps=fps,
                    input=file,
                    thumb=thumb,
                    output=output,
                    )

        os.system('cmd /c "{executable} -y -loglevel warning {args}"'.format(
            executable=ffmpeg_path,
            args=args,
                )
            )
        print('==> Thumbnail created! [{}]'.format(datetime.now()-start))
        return output


    def createFilmstrip(self, fps, file, interval, num_frames, version):
        start = datetime.now()
        output=os.path.join(version, os.path.basename(file).replace('.mov', '_filmstrip.jpg'))



        args = " \
            -r {fps} \
            -i {input} \
            -frames 1 \
            -vf \"scale=240:-1,select=not(mod(n\\,{interval})),tile={num_frames}x1\" \
            {output} \
                ".format(
                    fps=fps,
                    input=file,
                    interval=interval if interval > 1 else 1,
                    num_frames=num_frames,
                    output=output,
                    )

        os.system('cmd /c "{executable} -y -loglevel warning -stats {args}"'.format(
            executable=ffmpeg_path,
            args=args,
                )
            )
        print('==> Filmstrip created! [{}]'.format(datetime.now()-start))
        return output


    def TranscodeFile(self, input, data):
        start = datetime.now()
        dir = os.path.dirname(input)
        transcodes = os.path.join(dir,'transcodes')
        if not os.path.isdir(transcodes):
            os.mkdir(transcodes)

        version = os.path.join(transcodes, os.path.splitext( os.path.basename(input) )[0])
        if not os.path.isdir(version):
            os.mkdir(version)

        mp4 = self.createMP4(data['fps'], input, version)
        webm = self.createWebM(data['fps'], input, version)
        thumbnail = self.createThumbnail(data['fps'], input, data['thumb'], version)
        filmstrip = self.createFilmstrip(data['fps'], input, data['interval'], data['num_frames'], version)
        print('====> Finished! [{}]'.format(datetime.now()-start))


    def findCubeFile(self, context):
        path = None
        filters = [
            ['entity.Shot.code', 'is', context.entity["name"]]
                ]

        if context.task:
            filters.append(['task.Task.content', 'is', context.task["name"]])
        elif ctx.step:
            filters.append(['task.Task.content', 'is', context.step["name"]])

        fields = ['published_file_type', 'path']
        order = [
            {'field_name': 'version_number',
             'direction': 'desc',}
             ]
        found = self.__app.sgtk.shotgun.find('PublishedFile', filters, fields, order)

        for f in found:
            if f['published_file_type']['name'] == 'Cube File':
                path = f['path']['local_path']
                
        if path != None:
            return path.replace('\\', '/')
        else:
            return None


    def retrieveComment(self, context, path):
        filters = [
            ['entity.Shot.code', 'is', context.entity["name"]]
                ]
        if context.task:
            filters.append(['task.Task.content', 'is', context.task["name"]])
        elif ctx.step:
            filters.append(['task.Task.content', 'is', context.step["name"]])

        fields = ['description', 'code', 'published_file_type']
        order = [
            {'field_name': 'version_number',
             'direction': 'desc',}
             ]
        found = self.__app.sgtk.shotgun.find('PublishedFile', filters, fields, order)

        # look for Nuke Script
        img_seq = os.path.basename(path)
        base = img_seq.split('.')[0]
        code = base.split('_')[:-1]
        version = base.split('_')[-1]
        nk = '{code}.{version}.nk'.format(
            code='_'.join(code),
            version=version,
            )

        comment = None
        for f in found:
            if f['published_file_type']['name'] == 'Nuke Script':
                if f['code'] == nk:
                    comment = f['description']

        print('\n'*3+'Found Comment: '+str(comment)+'\n'*3)
        self.__app.log_debug('\n'*3+'Found Comment: '+str(comment)+'\n'*3)

        return comment
