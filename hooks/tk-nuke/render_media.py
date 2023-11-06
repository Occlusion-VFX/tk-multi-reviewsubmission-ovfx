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
from pprint import pprint
import re

HookBaseClass = sgtk.get_hook_baseclass()

ffmpeg_path = "V:/Scripts/FFMPEG/FFMPEG_Current/bin/ffmpeg.exe"

### getting path to config root
filepath = os.path.abspath(__file__)
dirPath = os.path.dirname(filepath)
configRoot = (os.sep).join(dirPath.split(os.sep)[:4])

#path to config/hooks to grab node
configHooks = os.path.join(configRoot, 'config', 'hooks')

# getting latest burn node
burnDir = os.path.join(
    configHooks, 'burnnode'
)
burnFiles = [ file for file in os.listdir(burnDir) if os.path.splitext(file)[-1] == '.nk' ]
burnFilename = burnFiles[-1]


class RenderMedia(HookBaseClass):
    """
    RenderMedia hook implementation for the tk-nuke engine.
    """

    def __init__(self, *args, **kwargs):
        super(RenderMedia, self).__init__(*args, **kwargs)

        self.__app = self.parent

        self._burnin_nk = os.path.join(
            # getting variables above before Class
            burnDir, burnFilename
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
        
        # collect all write nodes, if needed when rendering comp with slate mov
        writeNodes = self.collectWriteNodes()

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
            else:
                cs = read['colorspace'].value()
                if cs[:7] == 'default':
                    text = cs.split(" ")[-1]
                    update = text.replace("(","").replace(")","")
                    color_space = update
                else:
                    color_space = cs

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
            print('\n\nUsing burnin node: {}\n\n'.format(burnFilename))
            burn = nuke.nodePaste(self._burnin_nk)
            if cubeFile is None:
                burn.setInput(0, scale if crop else read)
            else:
                burn.setInput(0, scale if crop else lut)

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
            prj = self.getProject(ctx.project['name'])
            description =  self.getShotDescription(prj, ctx.entity['name'])
            clientVersion = self.getClientVersionNumber(prj, ctx.entity['name'])
            if clientVersion != None:
                verSlate = clientVersion
            else:
                verSlate = int(version)
                
            current_user = sgtk.util.get_current_user(self.__app.sgtk)
            print('parsing filename and filetype')
            filename, filetype = os.path.splitext(os.path.basename(input_path))
            print('==> {}, {}'.format(filename, filetype))
            comment = self.retrieveComment(ctx, input_path,)
            
            burnDict = {
                "project": ctx.project['name'],
                "shotCode": ctx.entity['name'],
                "dateSlate": datetime.today().strftime('%m.%d.%Y'), # dt.strftime('%m/%d/%y')
                "ffSlate": first_frame,
                "lfSlate": last_frame,
                "colorspace": color_space,
                "artist": current_user['name'],
                "fnSlate": filename.split('.')[0],
                "version": verSlate,
                "VersionPadding": int(self.__app.get_setting("version_number_padding")),
                "task": ctx.task["name"],
                "submission": "Final",
                "scope": description,
                "message": comment,
            }

            print("*"*30+'\n'*3)
            for knob in burnDict:
                print(knob, burnDict[knob])
                burn[knob].setValue(burnDict[knob])
            print("*"*30+'\n'*3)

            # render check format and render out approriate full frame slate
            # outputs render to Publish folder
            # ex: V:/Projects/Project_Data/[ project ]/sequences/[ seq ]/[ shot ]/comp/publish/elements/[ name ]/[ format ]/[ ext ]/[ filename ]


            print('Setting up comp format render')
            if filetype == '.mov':
                self.movSlateRender(
                    read,
                    first_frame,
                    last_frame,
                    burn,
                    writeNodes,
                    burn['comp_slate'].value(),
                )
            else:
                self.exrSlateRender(
                    read,
                    first_frame,
                    burn,
                    writeNodes,                    
                    burn['comp_slate'].value()
                    )

            # create a scale node
            scale = self.__create_scale_node(width, height)
            scale.setInput(0, burn)

            # Create the output node
            output_node = self.__create_output_node(output_path)

            # Match slate color to output colorspace of mov
            output_color = output_node['colorspace'].value()
            print(output_color)

            burn['colorspace'].setValue(output_color)
            output_node.setInput(0, scale)
            print("*"*30+'\n'*3)

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
                settings['colorspace'] = 'sRGB'
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


    def getShotDescription(self, project, shot):
        print('\n'+'*'*10+' Getting Shot Scope')
        filters = [
            ['project', 'is', project],
            ['code', 'is', shot],
        ]
        fields = ['code', 'description', 'project', 'sg_client_version']
        order = []
        found = self.__app.sgtk.shotgun.find_one('Shot', filters, fields, order)

        description = found['description']
        print(description)
        print('*'*10+' Found Shot Scope' + '\n')
        return description


    def getClientVersionNumber(self, project, shot):
        print('\n'+'*'*10+' Getting Client Version')
        filters = [
            ['project', 'is', project],
            ['code', 'is', shot],
        ]
        fields = ['code', 'description', 'project', 'sg_client_version']
        order = []
        found = self.__app.sgtk.shotgun.find_one('Shot', filters, fields, order)

        versionNum = found['sg_client_version']
        print('*'*10+' Found Client Version [{}]'.format(versionNum) + '\n')

        return versionNum


    def getProject(self, projectName): 
        filters = []
        fields = ['name']
        order = []
        projects = self.__app.sgtk.shotgun.find('Project', filters, fields, order)
        for project in projects:
            if project['name'].lower() == projectName.lower():
                currProject = project
        return currProject

    
    def exrSlateRender(self, readNode, first_frame, slateNode, allWrites, render):
        print('\n\nRendering Exr Slate Frame')
        """
        Create output node and render slate frame.

        :param snodetr readNode:         Input nuke read node
        :param int first_frame:          First Frame of input
        :param node slateNode:           Burnin/Slate Group node from Group

        :returns:               None
        :rtype:                 None
        """
        # read metadata and get path from Read Node
        filepath = readNode.knob('file').getText()
        readMeta = readNode.metadata()
        simplified = dict()

        filetype, settings = self.findWriteSettings(filepath, allWrites)

        for data in readMeta:
            key,name = data.split('/')
            simplified[name] = readMeta[data]

        colorspace = settings['colorspace']
        if readNode['colorspace'].value() != colorspace:
            readNode['colorspace'].setValue(colorspace)
            slateNode['colorspace'].setValue(colorspace)

        # Create and set write node
        writeNode = nuke.nodes.Write()
        writeNode.knob('file').setValue(filepath)
        writeNode.knob('file_type').setValue(simplified['filereader'])
        if simplified['filereader'] == 'exr':
            writeNode.knob('compression').setValue(simplified['compressionName'])
        writeNode.knob('datatype').setValue(simplified['bitsperchannel'])
        writeNode.knob('colorspace').setValue(colorspace)

        mainView = nuke.views()[0]

        writeNode.setInput(0, slateNode)

        if render:
            # check if script in proxy and toggle
            root_node = nuke.root()
            is_proxy = root_node["proxy"].value()
            if is_proxy:
                root_node["proxy"].setValue(0)
            
            # write slate frame
            nuke.executeMultiple(
                [writeNode], ([first_frame - 1, first_frame - 1, 1],), [mainView]
            )

            # toggle proxy if previously on
            if is_proxy:
                root_node["proxy"].setValue(1)

            print('==> Slate Frame render complete! [{}, {}]\n\n'.format(filepath,(first_frame - 1)))
 

    def movSlateRender(self, readNode, first_frame, last_frame, slateNode, allWrites, render):
        print('\n\nRendering Mov with Slate Frame')
        """
        Create output node and render mov with slate.

        :param snodetr readNode:         Input nuke read node
        :param int first_frame:          First Frame of input
        :param node slateNode:           Burnin/Slate Group node from Group
        :param list allWrites:           list of all write nodes in current Nuke Script


        :returns:               None
        :rtype:                 None
        """
        writeNodes = allWrites
        path = readNode['file'].getValue()
        filetype, settings = self.findWriteSettings(path, writeNodes)
        writeNode = self.createWriteNode(path, filetype, settings)

        colorspace = settings['colorspace']
        if readNode['colorspace'].value() != colorspace:
            readNode['colorspace'].setValue(colorspace)
            slateNode['colorspace'].setValue(colorspace)

        writeNode.setInput(0, slateNode)
        mainView = nuke.views()[0]

        # check if script in proxy and toggle
        root_node = nuke.root()
        is_proxy = root_node["proxy"].value()
        if is_proxy:
            root_node["proxy"].setValue(0)

        if render:
            # turn off burn in's for comp range
            burnToggle = slateNode['burn_toggle'].value()
            slateNode['burn_toggle'].setValue(False)
            
            # write slate frame
            nuke.executeMultiple(
                [writeNode], ([first_frame - 1, last_frame, 1],), [mainView]
            )

            # re-apply previous burn toggle status
            slateNode['burn_toggle'].setValue(burnToggle)

            # toggle proxy if previously on
            if is_proxy:
                root_node["proxy"].setValue(1)

            print('==> Comp with Slate render complete! [{}]\n\n'.format(writeNode['file'].value()))
            return writeNode


    def collectWriteNodes(self,):
        print('\nCollecting write nodes')
        allNodes = nuke.allNodes()
        writeNodes = []
        for node in allNodes:
            if node.Class() == 'Write':
                writeNodes.append(node)
            elif node.Class() == 'WriteTank':
                writeNodes.append(node)
        print('=> Found [{}] Write Nodes'.format(len(writeNodes)))
        return writeNodes


    def nukeWriteParse(self, node, debug=False):
        knobs = node.knobs()
        if debug:
            for knob in knobs:
                    print(knob, knobs[knob].value())
        
        file = node['file'].value()
        filetype = node['file_type'].value()
        settingVars = [
            'create_directories',
            'colorspace',
            # 'mov64_codec',
            'channels',
        ]
        if filetype == 'mov':
            settingVars.append('mov64_codec')

        if node['mov64_codec'].value() == 'AVdn':
            print('DNxHD Mov')
            settingVars.append('mov64_dnxhr_codec_profile')
        if node['mov64_codec'].value() == 'appr':
            print('Apple ProRes Mov')
            settingVars.append('mov_prores_codec_profile')


        writeSettings = {}
        for var in settingVars:
            writeSettings[var] = node[var].value()
        pprint(writeSettings)

        return writeSettings


    def shotgridWriteParse(self, node, debug=False):
        knobs = node.knobs()
        if debug:
            for knob in knobs:
                print(knob, node[knob].value())
            print('')

        settings = node['tk_file_type_settings'].value()
        filetype = node['tk_file_type'].value()

        ''' 
        cleaning preset sgtk settings string
        from (dp1\nS'mov_prores_codec_profile'\np2\nS'ProRes 4:4:4:4 XQ 12-bit'\np3\nsS'meta_encoder'\np4\nS'mov64'
            \np5\nsS'colorspace'\np6\nS'sRGB'\np7\nsS'mov64_codec'\np8\nS'appr'\np9\nsS'create_directories'\np10\nI01\ns.
        to list of settings
        '''
        cleaned = re.findall(r"\'(.+?)\'", str(settings))

        # setting up directory of settings
        name = cleaned[::2] 
        variable = cleaned[1::2]
        writeSettings = {}
        for i, n in enumerate(name):
            if n == 'create_directories':
                writeSettings[n] = True
            else:
                writeSettings[n] = variable[i]

        # applying settings grabbed directly from node
        writeSettings['channels'] = node['channels'].value()

        '''
        clean default from colorspace if it exists
        '''
        try:
           if node['colorspace'].value().split(' ')[0].lower() == 'default':
                cs = re.findall( 
                   r"(?<=\()(.*?)(?=\))",
                   str(node['colorspace'].value())
                )[0]
        except:
            cs = node['colorspace'].value()

        writeSettings['colorspace'] = cs
        print(node.name())   
        pprint(writeSettings)

        return writeSettings


    def findWriteSettings(self, path, nodes, debug=False):
        print('\nlooking through read nodes\n')
        reviewFN = os.path.basename(path)
        foundNode = None
        for node in nodes:
            if node.Class() == 'WriteTank':
                print('\nFound ShotGrid Write: {}'.format(node.name())) 
                filename = node['path_filename'].value()
                if reviewFN == filename:
                    filetype = node['tk_file_type'].value()
                    writeSettings = self.shotgridWriteParse(node, debug=debug)
                    foundNode = node
                else:
                    print('Does not match source\n{}:{}'.format(reviewFN,filename))
            else:
                print('\nStandard Write Node: {}'.format(node.name()))
                filename = os.path.basename(node['file'].value())

                if reviewFN == filename:
                    filetype = node['file_type'].value()
                    writeSettings = self.nukeWriteParse(node, debug=debug)
                    foundNode = node
                else:
                    print('Does not match source\n{}:{}'.format(reviewFN,filename))

        if foundNode == None:
            print('No matching write node')
            return None, None
        else:
            print('\n\nUsing Node: {}'.format(foundNode.name()))
            return filetype, writeSettings


    def createWriteNode(self, path, filetype, settings, debug=False):
        print('Creating Write Node')
        writeNode = nuke.nodes.Write()
        writeNode['file'].setValue(path.replace('.mov', '_slate.mov'))
        writeNode['file_type'].setValue(filetype)

        for s in settings:
            print(s, settings[s])
            if s == 'colorspace':
                try:
                    colorspace = re.findall(r'\((.*?)\)', settings[s])[0]
                except:
                    colorspace = settings[s]
                writeNode[s].setValue(colorspace)
            else:
                writeNode[s].setValue(settings[s])

        return writeNode