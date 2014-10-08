# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Sgtk Application for handling Quicktime generation and review submission
"""

import sgtk
import sgtk.templatekey
import copy
import os

class MultiReviewSubmissionApp(sgtk.platform.Application):
    """
    Main Application class
    """

    def init_app(self):
        """
        App initialization
        
        Note, this app doesn't register any commands at the moment as all it's functionality is
        provided through it's API.
        """
        pass

    def render_and_submit(self, template, fields, first_frame, last_frame, sg_publishes, sg_task,
                          comment, thumbnail_path, progress_cb):
        """
        Main application entry point to be called by other applications / hooks.

        :param template:        The template defining the path where frames should be found.
        :param fields:          Dictionary of fields to be used to fill out the template with.
        :param first_frame:     The first frame of the sequence of frames.
        :param last_frame:      The last frame of the sequence of frames.
        :param sg_publishes:    A list of shotgun published file objects to link the publish against.
        :param sg_task:         A Shotgun task object to link against. Can be None.
        :param comment:         A description to add to the Version in Shotgun. 

        :returns:               The Version Shotgun entity dictionary that was created.
        """
        tk_multi_reviewsubmission = self.import_module("tk_multi_reviewsubmission")
        
        # Is the app configured to do anything?
        upload_to_shotgun = self.get_setting("upload_to_shotgun")
        store_on_disk = self.get_setting("store_on_disk")
        if not upload_to_shotgun and not store_on_disk:
            self.log_warning("App is not configured to store images on disk nor upload to shotgun!")
            return None

        progress_cb(10, "Preparing")

        # Make sure we don't overwrite the caller's fields
        fields = copy.copy(fields)

        # Tweak fields so that we'll be getting nuke formated sequence markers (%03d, %04d etc):
        for key_name in [key.name for key in template.keys.values() if isinstance(key, sgtk.templatekey.SequenceKey)]:
            fields[key_name] = "FORMAT: %d"

        # Get our input path for frames to convert to movie
        path = template.apply_fields(fields)

        # Movie output width and height
        width = self.get_setting("movie_width")
        height = self.get_setting("movie_height")
        fields["width"] = width
        fields["height"] = height

        # Get an output path for the movie.
        output_path_template = self.get_template("movie_path_template")
        output_path = output_path_template.apply_fields(fields)

        # Render and Submit
        progress_cb(20, "Rendering movie")
        renderer = tk_multi_reviewsubmission.Renderer()
        renderer.render_movie_in_nuke(path, 
                                      output_path, 
                                      width, height, 
                                      first_frame, last_frame,
                                      fields.get("version", 0), 
                                      fields.get("name", "Unnamed"))

        progress_cb(50, "Creating Shotgun Version and uploading movie")
        submitter = tk_multi_reviewsubmission.Submitter()
        sg_version = submitter.submit_version(path, 
                                               output_path,
                                               thumbnail_path,
                                               sg_publishes, 
                                               sg_task, 
                                               comment, 
                                               store_on_disk,
                                               first_frame, 
                                               last_frame,
                                               upload_to_shotgun)
            
        # Remove from filesystem if required
        if not store_on_disk and os.path.exists(output_path):
            os.unlink(output_path)

        return sg_version
