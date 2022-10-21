#!/usr/bin/env python

# ViaStitching for pcbnew 
# This is the plugin WX dialog
# (c) Michele Santucci 2019
#
import random

import wx
import pcbnew
import gettext
import math

from .viastitching_gui import viastitching_gui
from math import sqrt
import numpy as np
import json
import pathlib

_ = gettext.gettext
__version__ = "0.2"
__timecode__ = 1972
__viagroupname__ = "VIA_STITCHING_GROUP"
default_filename = "defaults.json"


class ViaStitchingDialog(viastitching_gui):
    """Class that gathers all the Gui controls."""

    def __init__(self, board):
        """Initialize the brand new instance."""

        super(ViaStitchingDialog, self).__init__(None)
        self.SetTitle(_(u"ViaStitching v{0}").format(__version__))
        self.Bind(wx.EVT_CLOSE, self.onCloseWindow)
        self.m_btnCancel.Bind(wx.EVT_BUTTON, self.onCloseWindow)
        self.m_btnOk.Bind(wx.EVT_BUTTON, self.onProcessAction)
        self.m_btnClear.Bind(wx.EVT_BUTTON, self.onClearAction)
        self.board = board
        self.randomize = False
        self.pcb_group = None
        self.clearance = 0
        self.board_edges = []
        self.default_file_path = f"{pathlib.Path(__file__).parent.resolve()}/{default_filename}"

        for d in pcbnew.GetBoard().GetDrawings():
            if d.GetLayerName() == 'Edge.Cuts':
                self.board_edges.append(d)

        # Search trough groups
        for group in self.board.Groups():
            if group.GetName() == __viagroupname__:
                self.pcb_group = group

        # Use the same unit set int PCBNEW
        self.ToUserUnit = None
        self.FromUserUnit = None
        units_mode = pcbnew.GetUserUnits()

        if units_mode == 0:
            self.ToUserUnit = pcbnew.ToMils
            self.FromUserUnit = pcbnew.FromMils
            self.m_lblUnit1.SetLabel(_(u"mils"))
            self.m_lblUnit2.SetLabel(_(u"mils"))
            self.m_txtVSpacing.SetValue("40")
            self.m_txtHSpacing.SetValue("40")
        elif units_mode == 1:
            self.ToUserUnit = pcbnew.ToMM
            self.FromUserUnit = pcbnew.FromMM
            self.m_lblUnit1.SetLabel(_(u"mm"))
            self.m_lblUnit2.SetLabel(_(u"mm"))
            self.m_txtVSpacing.SetValue("1")
            self.m_txtHSpacing.SetValue("1")
        elif units_mode == -1:
            wx.MessageBox(_(u"Not a valid frame"))
            self.Destroy()

        try:
            defaults = {}
            with open(self.default_file_path, "r") as def_file:
                defaults = json.load(def_file)
        except Exception:
            pass

        self.m_txtVSpacing.SetValue(defaults.get("VSpacing", "3"))
        self.m_txtHSpacing.SetValue(defaults.get("HSpacing", "3"))
        self.m_txtClearance.SetValue(defaults.get("Clearance", "0"))
        self.m_chkRandomize.SetValue(defaults.get("Randomize", False))

        # Get default Vias dimensions
        via_dim_list = self.board.GetViasDimensionsList()

        if via_dim_list:
            via_dims = via_dim_list.pop()
        else:
            wx.MessageBox(_(u"Please set via drill/size in board"))
            self.Destroy()

        self.m_txtViaSize.SetValue("%.6f" % self.ToUserUnit(via_dims.m_Diameter))
        self.m_txtViaDrillSize.SetValue("%.6f" % self.ToUserUnit(via_dims.m_Drill))
        via_dim_list.push_back(via_dims)
        self.area = None
        self.net = None
        self.overlappings = None

        # Check for selected area
        if not self.GetAreaConfig():
            wx.MessageBox(_(u"Please select a valid area"))
            self.Destroy()
        else:
            # Populate nets checkbox
            self.PopulateNets()

    def GetOverlappingItems(self):
        """Collect overlapping items.
            Every bounding box of any item found is a candidate to be inspected for overlapping.
        """

        area_bbox = self.area.GetBoundingBox()

        if hasattr(self.board, 'GetModules'):
            modules = self.board.GetModules()
        else:
            modules = self.board.GetFootprints()

        tracks = self.board.GetTracks()

        self.overlappings = []

        for zone in self.board.Zones():
            if zone.GetZoneName() != self.area.GetZoneName():
                if (zone.GetBoundingBox().Intersects(area_bbox)):
                    self.overlappings.append(zone)

        for item in tracks:
            if (type(item) is pcbnew.PCB_VIA) and (item.GetBoundingBox().Intersects(area_bbox)):
                self.overlappings.append(item)
            if type(item) is pcbnew.PCB_TRACK:
                self.overlappings.append(item)

        for item in modules:
            if item.GetBoundingBox().Intersects(area_bbox):
                for pad in item.Pads():
                    self.overlappings.append(pad)
                for zone in item.Zones():
                    self.overlappings.append(zone)

        # TODO: change algorithm to 'If one of the candidate area's edges overlaps with target area declare candidate as overlapping'
        for i in range(0, self.board.GetAreaCount()):
            item = self.board.GetArea(i)
            if item.GetBoundingBox().Intersects(area_bbox):
                if item.GetNetname() != self.net:
                    self.overlappings.append(item)

    def GetAreaConfig(self):
        """Check selected area (if any) and verify if it is a valid container for vias.

        Returns:
            bool: Returns True if an area/zone is selected and match implant criteria, False otherwise.
        """

        for i in range(0, self.board.GetAreaCount()):
            area = self.board.GetArea(i)
            if area.IsSelected():
                if not area.IsOnCopperLayer():
                    return False
                elif area.GetDoNotAllowCopperPour():
                    return False
                self.area = area
                self.net = area.GetNetname()
                return True

        return False

    def PopulateNets(self):
        """Populate nets widget."""

        nets = self.board.GetNetsByName()

        # Tricky loop, the iterator should return two values, unluckly I'm not able to use the
        # first value of the couple so I'm recycling it as netname.
        for netname, net in nets.items():
            netname = net.GetNetname()
            if (netname != None) and (netname != ""):
                self.m_cbNet.Append(netname)

        # Select the net used by area (if any)
        if self.net != None:
            index = self.m_cbNet.FindString(self.net)
            self.m_cbNet.Select(index)

    def ClearArea(self):
        """Clear selected area."""

        undo = self.m_chkClearOwn.IsChecked()
        drillsize = self.FromUserUnit(float(self.m_txtViaDrillSize.GetValue()))
        viasize = self.FromUserUnit(float(self.m_txtViaSize.GetValue()))
        netname = self.m_cbNet.GetStringSelection()
        netcode = self.board.GetNetcodeFromNetname(netname)
        #commit = pcbnew.COMMIT()
        viacount = 0

        for item in self.board.GetTracks():
            if type(item) is pcbnew.PCB_VIA:
                # If the user selected the Undo action only signed/grouped vias are removed,
                # otherwise are removed vias matching values set in the dialog.

                # if undo and (item.GetTimeStamp() == __timecode__):
                if undo and (self.pcb_group is not None):
                    group = item.GetParentGroup()
                    if (group is not None and group.GetName() == __viagroupname__):
                        self.board.Remove(item)
                        viacount += 1
                        # commit.Remove(item)
                elif (not undo) and self.area.HitTestFilledArea(self.area.GetLayer(), item.GetPosition(), 0) and (
                        item.GetDrillValue() == drillsize) and (item.GetWidth() == viasize) and (
                        item.GetNetname() == netname):
                    self.board.Remove(item)
                    self.pcb_group.RemoveItem(item)
                    viacount += 1
                    # commit.Remove(item)

        if viacount > 0:
            wx.MessageBox(_(u"Removed: %d vias!") % viacount)
            #commit.Push()
            pcbnew.Refresh()

    def CheckClearance(self, via, area, clearance):
        """Check if position specified by p1 comply with given clearance in area.

        Parameters:
            p1 (wxPoint): Position to test
            area (pcbnew.ZONE_CONTAINER): Area
            clearance (int): Clearance value

        Returns:
            bool: True if p1 position comply with clearance value False otherwise.

        """
        p1 = via.GetPosition()
        corners = area.GetNumCorners()
        # Calculate minimum distance from corners
        # TODO: remove?
        for i in range(corners):
            corner = area.GetCornerPosition(i)
            p2 = corner.getWxPoint()
            the_distance = np.linalg.norm(p2 - p1)  # sqrt((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2)

            if the_distance < clearance:
                return False

        point = np.array([float(p1.x), float(p1.y)])  # Calculate minimum distance from edges
        for i in range(corners):
            corner1 = area.GetCornerPosition(i)
            corner2 = area.GetCornerPosition((i + 1) % corners)
            pc1 = corner1.getWxPoint()
            pc2 = corner2.getWxPoint()
            # start = np.array([float(pc1.x), float(pc1.y), 0.])
            # end = np.array([float(pc2.x), float(pc2.y), 0.])
            the_distance, _ = pnt2line(p1, pc1, pc2)

            if the_distance <= clearance:
                return False

        for edge in self.board_edges:
            if edge.ShowShape() == 'Line':
                # start = np.array([float(edge.GetStart().x), float(edge.GetStart().y), 0.])
                # end = np.array([float(edge.GetEnd().x), float(edge.GetEnd().y), 0.])
                the_distance, _ = pnt2line(p1, edge.GetStart(), edge.GetEnd())
                if the_distance <= clearance + via.GetWidth() / 2:
                    return False
            if edge.ShowShape() == 'Arc':
                # distance from center of Arc and with angle within Arc angle should be outside Arc radius +- clearance + via Width/2
                center = edge.GetPosition()
                start = edge.GetStart()
                end = edge.GetEnd()
                radius = np.linalg.norm(center - end)  # ((center - end).x ** 2 + (center - end).y ** 2)
                dist = np.linalg.norm(p1 - center)  # sqrt((p1 - center).x ** 2 + (p1 - center).y ** 2)
                if radius - (self.clearance + via.GetWidth() / 2) < dist < radius + (
                        self.clearance + via.GetWidth() / 2):
                    # via is in range need to check the angle
                    start_angle = math.atan2((start - center).y, (start - center).x)
                    end_angle = math.atan2((end - center).y, (end - center).x)
                    if end_angle < start_angle:
                        end_angle += 2*math.pi
                    point_angle = math.atan2((p1 - center).y, (p1 - center).x)
                    if start_angle <= point_angle <= end_angle:
                        return False

        return True

    def CheckOverlap(self, via):
        """Check if via overlaps or interfere with other items on the board.

        Parameters:
            via (pcbnew.VIA): Via to be checked

        Returns:
            bool: True if via overlaps with an item, False otherwise.
        """

        for item in self.overlappings:
            if type(item) is pcbnew.PAD:
                if item.GetBoundingBox().Intersects(via.GetBoundingBox()):
                    return True
            elif type(item) is pcbnew.PCB_VIA:
                # Overlapping with vias work best if checking is performed by intersection
                if item.GetBoundingBox().Intersects(via.GetBoundingBox()):
                    return True
            elif type(item) in [pcbnew.ZONE, pcbnew.FP_ZONE]:
                if item.HitTestFilledArea(self.area.GetLayer(), via.GetPosition(), 0):
                    return True
            elif type(item) is pcbnew.PCB_TRACK:
                if item.GetBoundingBox().Intersects(via.GetBoundingBox()):
                    width = item.GetWidth()
                    dist, _ = pnt2line(via.GetPosition(), item.GetStart(), item.GetEnd())
                    if dist <= self.clearance + width // 2 + via.GetWidth() / 2:
                        return True
        return False

    def FillupArea(self):
        """Fills selected area with vias."""

        drillsize = self.FromUserUnit(float(self.m_txtViaDrillSize.GetValue()))
        viasize = self.FromUserUnit(float(self.m_txtViaSize.GetValue()))
        step_x = self.FromUserUnit(float(self.m_txtHSpacing.GetValue()))
        step_y = self.FromUserUnit(float(self.m_txtVSpacing.GetValue()))
        clearance = self.FromUserUnit(float(self.m_txtClearance.GetValue()))
        self.randomize = self.m_chkRandomize.GetValue()
        self.clearance = clearance
        bbox = self.area.GetBoundingBox()
        top = bbox.GetTop()
        bottom = bbox.GetBottom()
        right = bbox.GetRight()
        left = bbox.GetLeft()
        netname = self.m_cbNet.GetStringSelection()
        netcode = self.board.GetNetcodeFromNetname(netname)
        # commit = pcbnew.COMMIT()
        viacount = 0
        x = left

        # Cycle trough area bounding box checking and implanting vias
        layer = self.area.GetLayer()

        while x <= right:
            y = top
            while y <= bottom:
                if self.randomize:
                    xp = x + random.uniform(-1, 1) * step_x / 5
                    yp = y + random.uniform(-1, 1) * step_y / 5
                else:
                    xp = x
                    yp = y
                p = pcbnew.wxPoint(xp, yp)
                if self.area.HitTestFilledArea(layer, p, 0):
                    via = pcbnew.PCB_VIA(self.board)
                    via.SetPosition(p)
                    via.SetLayer(layer)
                    via.SetNetCode(netcode)
                    # Set up via with clearance added to its size-> bounding box check will be OK in worst case, may be too conservative, but additional checks are possible if needed
                    # TODO: possibly take the clearance from the PCB settings instead of the dialog
                    # Clearance is all around -> *2
                    via.SetDrill(drillsize + 2 * clearance)
                    via.SetWidth(viasize + 2 * clearance)
                    # via.SetTimeStamp(__timecode__)
                    if not self.CheckOverlap(via):
                        # Check clearance only if clearance value differs from 0 (disabled)
                        if (clearance == 0) or self.CheckClearance(via, self.area, clearance):
                            via.SetWidth(viasize)
                            via.SetDrill(drillsize)
                            self.board.Add(via)
                            # commit.Add(via)
                            self.pcb_group.AddItem(via)
                            viacount += 1
                y += step_y
            x += step_x

        if viacount > 0:
            wx.MessageBox(_(u"Implanted: %d vias!") % viacount)
            # commit.Push()
            pcbnew.Refresh()
        else:
            wx.MessageBox(_(u"No vias implanted!"))

    def onProcessAction(self, event):
        """Manage main button (Ok) click event."""

        config = {"HSpacing": self.m_txtHSpacing.GetValue(),
                  "VSpacing": self.m_txtVSpacing.GetValue(),
                  "Clearance": self.m_txtClearance.GetValue(),
                  "Randomize": self.m_chkRandomize.GetValue()}

        with open(self.default_file_path, "w+") as def_file:
            def_file.write(json.dumps(config))

        # Get overlapping items
        self.GetOverlappingItems()

        # Search trough groups
        for group in self.board.Groups():
            if group.GetName() == __viagroupname__:
                self.pcb_group = group

        if self.pcb_group is None:
            self.pcb_group = pcbnew.PCB_GROUP(None)
            self.pcb_group.SetName(__viagroupname__)
            self.board.Add(self.pcb_group)

        self.FillupArea()
        self.Destroy()

    def onClearAction(self, event):
        """Manage clear vias button (Clear) click event."""

        self.ClearArea()
        self.Destroy()

    def onCloseWindow(self, event):
        """Manage Close button click event."""

        self.Destroy()


def InitViaStitchingDialog(board):
    """Initalize dialog."""

    dlg = ViaStitchingDialog(board)
    dlg.Show(True)
    return dlg

# Given a line with coordinates 'start' and 'end' and the
# coordinates of a point 'point' the proc returns the shortest
# distance from pnt to the line and the coordinates of the
# nearest point on the line.
#
# 1  Convert the line segment to a vector ('line_vec').
# 2  Create a vector connecting start to pnt ('pnt_vec').
# 3  Find the length of the line vector ('line_len').
# 4  Convert line_vec to a unit vector ('line_unitvec').
# 5  Scale pnt_vec by line_len ('pnt_vec_scaled').
# 6  Get the dot product of line_unitvec and pnt_vec_scaled ('t').
# 7  Ensure t is in the range 0 to 1.
# 8  Use t to get the nearest location on the line to the end
#    of vector pnt_vec_scaled ('nearest').
# 9  Calculate the distance from nearest to pnt_vec_scaled.
# 10 Translate nearest back to the start/end line.
# Malcolm Kesson 16 Dec 2012

def pnt2line(point: pcbnew.wxPoint, start: pcbnew.wxPoint, end: pcbnew.wxPoint):
    pnt = np.array([point.x, point.y])
    strt = np.array([start.x, start.y])
    nd = np.array([end.x, end.y])
    line_vec = nd - strt
    pnt_vec = pnt - strt
    line_len = np.linalg.norm(line_vec)
    line_unitvec = line_vec/line_len
    pnt_vec_scaled = pnt_vec/line_len
    t = np.dot(line_unitvec, pnt_vec_scaled)
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    nearest = line_vec * t
    dist = np.linalg.norm(pnt_vec - nearest)
    nearest = nearest + strt
    return dist, nearest
