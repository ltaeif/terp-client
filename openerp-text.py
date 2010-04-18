#!/usr/bin/python
##############################################################################
#
#    OpenERP-Text: Text-Mode Client for OpenERP
#    Copyright (C) 2010 David Janssens <david.j@almacom.co.th>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from optparse import OptionParser
import curses
import curses.textpad
import curses.panel
import sys
import time
import xmlrpclib
import xml.etree.ElementTree
import pdb
import traceback

parser=OptionParser()
parser.add_option("-H","--host",dest="host",help="host name",metavar="HOST",default="127.0.0.1")
parser.add_option("-P","--port",dest="port",help="port number",metavar="HOST",default=8069)
parser.add_option("-d","--db",dest="dbname",help="database",metavar="DB")
parser.add_option("-u","--uid",dest="uid",help="user ID",metavar="UID",default=1)
parser.add_option("-p","--passwd",dest="passwd",help="user password",metavar="PASSWD",default="admin")
parser.add_option("--debug",action="store_true",dest="debug",help="debug mode",default=False)
(opts,args)=parser.parse_args()

if opts.debug:
    def ex_info(type,value,tb):
        traceback.print_exception(type,value,tb)
        pdb.pm()
    sys.excepthook=ex_info

rpc=xmlrpclib.ServerProxy("http://%s:%d/xmlrpc/object"%(opts.host,opts.port))

dbname=opts.dbname
if not dbname:
    raise Exception("Missing dbname")
uid=opts.uid
passwd=opts.passwd

screen=None
tab_panel=None

def log(*args):
    msg=" ".join([str(a) for a in args])
    screen.addstr(msg+"\n")
    screen.refresh()

def rpc_exec(*args):
    try:
        return rpc.execute(dbname,uid,passwd,*args)
    except Exception,e:
        raise Exception("RPC failed: %s %s %s %s\n%s"%(dbname,uid,passwd,str(args),str(e)))

def set_trace():
    curses.nocbreak()
    screen.keypad(0)
    curses.echo()
    curses.endwin()
    pdb.set_trace()

def eval_dom(dom,obj):
    for (name,oper,param) in dom:
        val=obj[name]
        if oper=="=":
            res=val==param
        elif oper=="!=":
            res=val!=param
        elif oper=="in":
            res=val in param
        elif oper=="not in":
            res=not val in param
        else:
            raise Exception("unsupported operator: %s"%oper)
        if not res:
            return False
    return True

class Widget(object):
    def __init__(self):
        self.x=None
        self.y=None
        self.w=None
        self.h=1
        self.maxw=-1
        self.borders=[0,0,0,0]
        self.align="left"
        self.cx=None
        self.cy=None
        self.can_focus=False
        self.has_focus=False
        self.field_attrs={}
        self.states_f={}
        self.view_attrs={}
        self.states_v=None
        self.attrs_v={}
        self.colspan=1
        self.string=""
        self.readonly=False
        self.invisible=False
        self.states=None

    def set_field_attrs(self,attrs):
        for k,v in attrs.items():
            if k in ("string","readonly","states","size","select","required","domain","relation","context","digits","change_default","help","selection"):
                self.field_attrs[k]=v
            elif k in ("views","type"):
                pass
            else:
                raise Exception("unsupported field attribute: %s"%k)
        for k,v in self.field_attrs.items():
            setattr(self,k,v)

    def set_view_attrs(self,attrs):
        for k,v in attrs.items():
            if k in ("string","name","on_change","domain","context","type","widget","mode","sum","icon","default_get"):
                val=v
            elif k in ("colspan","col"):
                val=int(v)
            elif k in ("readonly","select","required","nolabel","invisible"):
                val=eval(v) and True or False
            elif k=="states":
                val=v.split(",")
            elif k=="attrs":
                val=eval(v)
            else:
                raise Exception("unsupported view attribute: %s"%k)
            self.view_attrs[k]=val
        for k,v in self.view_attrs.items():
            setattr(self,k,v)

    def set_vals(self,vals):
        self.update_attrs(vals)

    def to_s(self,d=0):
        s="  "*d
        s+=" "+self.__class__.__name__
        for name in dir(self):
            if name.startswith("_"):
                continue
            val=getattr(self,name)
            if callable(val):
                continue
            s+=" %s=%s"%(name,str(val))
        return s

    def draw(self,win):
        pass

    def set_focus(self):
        if self.can_focus and not self.readonly:
            self.has_focus=True
            screen.move(self.y,self.x)
            return self
        else:
            return None

    def get_focused(self):
        if self.has_focus:
            return self
        return None

    def get_tabindex(self):
        if self.can_focus and not self.readonly:
            return [self]
        else:
            return []

    def key_pressed(self,k):
        pass

class Panel(Widget):
    def __init__(self):
        super(Panel,self).__init__()
        self._childs=[]
        self._focused_wg=None

    def add(self,wg):
        self._childs.append(wg)
        if not self._focused_wg and wg.can_focus:
            self._focused_wg=wg

    def to_s(self,d=0):
        s=super(Panel,self).to_s(d)
        for c in self._childs:
            s+="\n"+c.to_s(d+1)
        return s

    def _vis_childs(self):
        for c in self._childs:
            if c.invisible:
                continue
            yield c

    def compute(self,w,y,x):
        self._compute_pass1()
        self.w=w
        self.y=y
        self.x=x
        self._compute_pass2()

    def draw(self,win):
        for c in self._vis_childs():
            c.draw(win)

    def set_vals(self,vals):
        super(Panel,self).set_vals(vals)
        for c in self._childs:
            c.set_vals(vals)

    def set_focus(self):
        wg_f=super(Panel,self).set_focus()
        if wg_f:
            return wg_f
        for wg in self._childs:
            wg_f=wg.set_focus()
            if wg_f:
                return wg_f
        return None

    def get_focused(self):
        if self.has_focus:
            return self
        for wg in self._childs:
            wg_f=wg.get_focused()
            if wg_f:
                return wg_f
        return None

    def get_tabindex(self):
        ind=super(Panel,self).get_tabindex()
        for wg in self._vis_childs():
            ind+=wg.get_tabindex()
        return ind

class DeckPanel(Panel):
    def __init__(self):
        super(DeckPanel,self).__init__()
        self.cur_wg=None

    def add(self,wg):
        super(DeckPanel,self).add(wg)
        if self.cur_wg==None:
            self.cur_wg=wg

    def _compute_pass1(self):
        if not self._childs:
            return
        for wg in self._vis_childs():
            if hasattr(wg,"_compute_pass1"):
                wg._compute_pass1()
        maxws=[wg.maxw for wg in self._vis_childs()]
        if -1 in maxws:
            self.maxw=-1
        else:
            self.maxw=max(maxws)+self.borders[1]+self.borders[3]
        self.h=max([wg.h for wg in self._vis_childs()])+self.borders[0]+self.borders[2]

    def _compute_pass2(self):
        w=self.w-self.borders[1]-self.borders[3]
        for wg in self._vis_childs():
            if wg.maxw==-1:
                wg.w=w
            else:
                wg.w=min(w,wg.maxw)
            wg.y=self.y+self.borders[0]
            wg.x=self.x+self.borders[3]
        for wg in self._vis_childs():
            if hasattr(wg,"_compute_pass2"):
                wg._compute_pass2()

    def draw(self,win):
        if not self.cur_wg:
            return
        self.cur_wg.draw(win)

    def set_focus(self):
        wg_f=Widget.set_focus(self)
        if wg_f:
            return wg_f
        if self.cur_wg:
            wg_f=self.cur_wg.set_focus()
            if wg_f:
                return wg_f
        return None

    def get_focused(self):
        if self.has_focus:
            return self
        if self.cur_wg:
            wg_f=self.cur_wg.get_focused()
            if wg_f:
                return wg_f
        return None

    def get_tabindex(self):
        ind=Widget.get_tabindex(self)
        if self.cur_wg:
            ind+=self.cur_wg.get_tabindex()
        return ind

class HorizontalPanel(Panel):
    def __init__(self):
        super(HorizontalPanel,self).__init__()

    def draw(self,win):
        pass

class Table(Panel):
    def __init__(self):
        super(Table,self).__init__()
        self.col=4
        self.num_rows=0
        self._childs=[]
        self._child_cx=0
        self._child_cy=0
        self.seps=[0,1]
        self.h_top=None
        self.w_left=None

    def add(self,wg):
        if wg.colspan>self.col:
            raise Exception("invalid colspan")
        if self._child_cx+wg.colspan>self.col:
            self._child_cy+=1
            self._child_cx=0
        wg.cy=self._child_cy
        wg.cx=self._child_cx
        self._child_cx+=wg.colspan
        self._childs.append(wg)
        self.num_rows=wg.cy+1

    def newline(self):
        self._child_cy+=1
        self._child_cx=0

    def _compute_pass1(self):
        if not self._childs:
            return
        for widget in self._vis_childs():
            if hasattr(widget,"_compute_pass1"):
                widget._compute_pass1()
        # 1. compute container max width
        expand=False
        for wg in self._vis_childs():
            if wg.maxw==-1:
                expand=True
                break
        if expand:
            self.maxw=-1
        else:
            w_left=[0]
            for i in range(1,self.col+1):
                w_max=w_left[i-1]
                for wg in self._vis_childs():
                    cr=wg.cx+wg.colspan
                    if cr!=i:
                        continue
                    w=w_left[wg.cx]+wg.maxw
                    if wg.cx>0:
                        w+=self.seps[1]
                    if w>w_max:
                        w_max=w
                w_left.append(w_max)
            self.maxw=self.borders[3]+self.borders[1]+w_left[-1]
        # 2. compute container height
        self.h_top=[0]
        for i in range(self.num_rows):
            h=0
            for wg in self._vis_childs():
                if wg.cy!=i:
                    continue
                if wg.h>h:
                    h=wg.h
            h+=self.h_top[-1]
            if i>0:
                h+=self.seps[0]
            self.h_top.append(h)
        self.h=self.borders[0]+self.h_top[-1]+self.borders[2]

    def _compute_pass2(self):
        if not self._childs:
            self.w=0
            return
        # 1. compute child widths
        w_avail=self.w-self.borders[3]-self.borders[1]
        for wg in self._vis_childs():
            wg.w=0
        w_left=[0]*(self.col+1)
        w_rest=w_avail
        # allocate space fairly to every child
        while w_rest>0:
            w_alloc=w_rest-self.seps[1]*(self.col-1)
            if w_alloc>self.col:
                dw=w_alloc/self.col
            else:
                dw=1
            incr=False
            for wg in self._vis_childs():
                if wg.maxw!=-1:
                    if not wg.w<wg.maxw:
                        continue
                    dw_=min(dw,wg.maxw-wg.w)
                else:
                    dw_=dw
                wg.w+=dw_
                incr=True
                w=w_left[wg.cx]+wg.w
                if wg.cx>0:
                    w+=self.seps[1]
                cr=wg.cx+wg.colspan
                if w>w_left[cr]:
                    dwl=w-w_left[cr]
                    for i in range(cr,self.col+1):
                        w_left[i]+=dwl
                    w_rest=w_avail-w_left[-1]
                    if w_rest==0:
                        break
            if not incr:
                break
        self.w_left=w_left
        # add extra cell space to regions
        for wg in self._vis_childs():
            if wg.maxw!=-1 and wg.w==wg.maxw:
                continue
            w=w_left[wg.cx]+wg.w
            if wg.cx>0:
                w+=self.seps[1]
            cr=wg.cx+wg.colspan
            if w<w_left[cr]:
                dw=w_left[cr]-w
                if wg.maxw!=-1:
                    dw=min(dw,wg.maxw-wg.w)
                wg.w+=dw
        # 2. compute child positions
        for wg in self._vis_childs():
            wg.y=self.y+self.borders[0]+self.h_top[wg.cy]+(wg.cy>0 and self.seps[0] or 0)
            if wg.align=="right":
                wg.x=self.x+self.borders[3]+w_left[wg.cx+wg.colspan]-wg.w
            else:
                wg.x=self.x+self.borders[3]+w_left[wg.cx]+(wg.cx>0 and self.seps[1] or 0)
        for child in self._vis_childs():
            if hasattr(child,"_compute_pass2"):
                child._compute_pass2()

class Form(Table):
    def __init__(self):
        super(Form,self).__init__()
        self.relation=None
        self.string=""

    def update_attrs(self,vals):
        state=vals.get("state")
        update=("readonly","required","invisible")
        for k,v in self.field_attrs.items():
            if k in update:
                setattr(self,k,v)
        states=self.field_attrs.get("states")
        if states and state in states:
            for k,v in states[state]:
                if k in update:
                    setattr(self,k,v)
                else:
                    raise Exception("attribute can not be updated: %s"%k)
        for k,v in self.view_attrs.items():
            if k in update:
                setattr(self,k,v)
        states=self.view_attrs.get("states")
        if states!=None:
            self.invisible=not state in states
        attrs=self.view_attrs.get("attrs")
        if attrs:
            for k,dom in attrs.items():
                if k in update:
                    setattr(self,k,eval_dom(dom,vals))
                else:
                    raise Exception("attribute can not be updated: %s"%k)

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        super(Form,self).draw(win)

    def key_pressed(self,k):
        wg_f=self.get_focused()
        if k in (ord("\t"),curses.KEY_DOWN):
            ind=self.get_tabindex()
            i=ind.index(wg_f)
            i=(i+1)%len(ind)
            ind[i].set_focus()
            wg_f.has_focus=False
        elif k==curses.KEY_UP:
            ind=self.get_tabindex()
            i=ind.index(wg_f)
            i=(i-1)%len(ind)
            ind[i].set_focus()
            wg_f.has_focus=False
        else:
            set_trace()
            wg_f.key_pressed(k)

class Group(Table):
    def __init__(self):
        super(Group,self).__init__()
        self.string=""

class Notebook(DeckPanel):
    def __init__(self):
        super(Notebook,self).__init__()
        self.can_focus=True

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        x=self.x+1
        i=0
        for wg in self._childs:
            if i==0:
                win.addch(self.y,x,curses.ACS_RTEE)
            else:
                win.addch(self.y,x,curses.ACS_VLINE)
            x+=1
            s=" "+wg.string+" "
            if self.cur_wg==wg:
                win.addstr(self.y,x,s,curses.A_BOLD)
            else:
                win.addstr(self.y,x,s)
            x+=len(s)
            i+=1
        win.addch(self.y,x,curses.ACS_LTEE)
        super(Notebook,self).draw(win)

    def set_focus(self):
        wg=super(Notebook,self).set_focus()
        if not wg:
            return None
        screen.move(self.y,self.x+3)

class Page(Table):
    def __init__(self):
        super(Page,self).__init__()

class ListView(Widget):
    def __init__(self):
        super(ListView,self).__init__()
        self.relation=None
        self.headers=[]
        self.sep=1
        self.h=8
        self.borders=[1,1,1,1]
        self.can_focus=True

    def update_attrs(self,vals):
        pass

    def _compute_pass1(self):
        self.col=len(self.headers)
        self.col_maxw=[]
        for name,string in self.headers:
            self.col_maxw.append(len(string))
        self.maxw=-1

    def _compute_pass2(self):
        self.col_w=[0]*self.col
        w_avail=self.w-self.borders[3]-self.borders[1]
        w_rest=w_avail
        while w_rest>0:
            w_alloc=w_rest-self.sep*(self.col-1)
            if w_alloc>self.col:
                dw=w_alloc/self.col
            else:
                dw=1
            incr=False
            for i in range(self.col):
                maxw=self.col_maxw[i]
                if maxw!=-1:
                    colw=self.col_w[i]
                    if not colw<maxw:
                        continue
                    dw_=min(dw,maxw-colw)
                else:
                    dw_=dw
                self.col_w[i]+=dw_
                w_rest-=dw_
                incr=True
                if not w_rest:
                    break
            if not incr:
                break
        self.col_x=[self.x+self.borders[3]]
        for i in range(1,self.col):
            self.col_x.append(self.col_x[i-1]+self.col_w[i-1]+self.sep)

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        for i in range(1,self.col):
            x=self.col_x[i]-1
            win.vline(self.y+1,x,curses.ACS_VLINE,self.h-2)
            win.addch(self.y,x,curses.ACS_TTEE)
            win.addch(self.y+self.h-1,x,curses.ACS_BTEE)
        for i in range(self.col):
            name,string=self.headers[i]
            s=string[:self.col_w[i]]
            win.addstr(self.y+1,self.col_x[i],s)

    def set_focus(self):
        wg=super(ListView,self).set_focus()
        if not wg:
            return None
        screen.move(self.y+2,self.x+1)

class TreeView(ListView):
    def __init__(self):
        super(TreeView,self).__init__()
        self.field_parent=None

    def set_vals(self,vals):
        self.objs=vals

    def draw(self,win):
        curses.textpad.rectangle(win,self.y,self.x,self.y+self.h-1,self.x+self.w-1)
        for i in range(1,self.col):
            x=self.col_x[i]-1
            win.vline(self.y+1,x,curses.ACS_VLINE,self.h-2)
            win.addch(self.y,x,curses.ACS_TTEE)
            win.addch(self.y+self.h-1,x,curses.ACS_BTEE)
        for i in range(self.col):
            name,string=self.headers[i]
            s=string[:self.col_w[i]]
            win.addstr(self.y+1,self.col_x[i],s)
        y=self.y+2
        for obj in self.objs:
            if obj[self.field_parent]:
                win.addstr(y,self.x+1,"/")
            for i in range(self.col):
                name=self.names[i]
                s=obj[name][:self.col_w[i]]
                win.addstr(y,self.col_x[i],s)
            y+=1

class Label(Widget):
    def __init__(self):
        super(Label,self).__init__()

    def _compute_pass1(self):
        self.maxw=len(self.string)

    def draw(self,win):
        win.addstr(self.y,self.x,self.string)

class Separator(Widget):
    def __init__(self):
        super(Separator,self).__init__()
        self.string=""

    def draw(self,win):
        pass

class Button(Widget):
    def __init__(self):
        super(Button,self).__init__()
        self.can_focus=True

    def _compute_pass1(self):
        self.maxw=len(self.string)+2

    def draw(self,win):
        s="["+self.string[:self.w-2]+"]"
        win.addstr(self.y,self.x,s)

    def set_focus(self):
        wg=super(Button,self).set_focus()
        if not wg:
            return None
        screen.move(self.y,self.x+1)

class FieldLabel(Widget):
    def __init__(self):
        super(FieldLabel,self).__init__()
        self.align="right"

    def _compute_pass1(self):
        self.maxw=len(self.string)+1

    def draw(self,win):
        s=self.string[:self.w-1]
        s+=":"
        win.addstr(self.y,self.x,s)

class Input(Widget):
    def __init__(self):
        super(Input,self).__init__()
        self.name=None
        self.value=False
        self.can_focus=True

    def set_vals(self,vals):
        super(Input,self).set_vals(vals)
        if self.name in vals:
            self.value=vals[self.name]

class InputChar(Input):
    def __init__(self):
        super(InputChar,self).__init__()
        self.size=None
        self.value=""

    def draw(self,win):
        if self.value!=False:
            s=self.value[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

    def validate(self,val):
        return val

class InputInteger(Input):
    def __init__(self):
        super(InputInteger,self).__init__()
        self.maxw=9

    def draw(self,win):
        if self.value!=False:
            s=str(self.value)[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputFloat(Input):
    def __init__(self):
        super(InputFloat,self).__init__()
        self.maxw=12

    def draw(self,win):
        if self.value!=False:
            s=str(self.value)[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputSelect(Input):
    def __init__(self):
        super(InputSelect,self).__init__()
        self.selection=[]

    def set_selection(self,sel):
        self.selection=sel
        self.maxw=0
        for k,v in sel:
            self.maxw=max(self.maxw,len(v))

    def draw(self,win):
        if self.value!=False:
            s=None
            for k,v in self.selection:
                if k==self.value:
                    s=v
                    break
            if not s:
                raise Exception("invalid selection value: %s"%self.value)
            s=s[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputText(Input):
    def __init__(self):
        super(InputText,self).__init__()
        self.height=5

    def draw(self,win):
        s=" "*self.w
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputBoolean(Input):
    def __init__(self):
        super(InputBoolean,self).__init__()
        self.maxw=1

    def draw(self,win):
        s=(self.value and "Y" or "N")[:self.w]
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputDate(Input):
    def __init__(self):
        super(InputDate,self).__init__()
        self.maxw=10

    def draw(self,win):
        if self.value!=False:
            s=self.value[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputDatetime(Input):
    def __init__(self):
        super(InputDatetime,self).__init__()
        self.maxw=19

    def draw(self,win):
        if self.value!=False:
            s=self.value[:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputM2O(Input):
    def __init__(self):
        super(InputM2O,self).__init__()
        self.relation=None

    def draw(self,win):
        if self.value!=False:
            s=self.value[1][:self.w]
        else:
            s=""
        s+=" "*(self.w-len(s))
        win.addstr(self.y,self.x,s,curses.A_UNDERLINE)

class InputO2M(DeckPanel):
    def __init__(self):
        super(InputO2M,self).__init__()
        self.relation=None
        self.tree=None
        self.form=None

    def add(self,wg,type="tree"):
        super(InputO2M,self).add(wg)
        if type=="tree":
            self.tree=wg
        elif type=="form":
            self.form=wg
        else:
            raise Exception("Unsupported view type: %s"%type)

    def _compute_pass1(self):
        super(InputO2M,self)._compute_pass1()
        self.h=self.tree.h

class InputM2M(Panel):
    def __init__(self):
        super(InputM2M,self).__init__()
        self.h=8
        self.relation=None

    def draw(self,win):
        pass

class TreeWindow(HorizontalPanel):
    def __init__(self):
        super(TreeWindow,self).__init__()
        self.field_parent=None
        self.root_list=ListView()
        self.add(self.root_list)

    def parse_tree(self,el,fields):
        if el.tag=="tree":
            wg=TreeView()
            names=[]
            for child in el:
                names.append(child.attrib["name"])
            wg.field_names=names
            return wg

    def load_view(self):
        self.view=rpc_exec(self.model,"fields_view_get",self.view_id,"tree",self.context)
        self.field_parent=self.view["field_parent"]
        self.fields=self.view["fields"]
        self.arch=xml.etree.ElementTree.fromstring(self.view["arch"])
        self.tree=self.parse_tree(self.arch,self.fields)
        self.add(self.tree)

    def load_data(self):
        self.root_ids=rpc_exec(self.model,"search",self.domain)
        self.root_objs=rpc_exec(self.model,"read",self.root_ids,["name",self.field_parent])
        self.root_list.set_vals(self.root_objs)
        self.obj_ids=self.root_objs[0][self.field_parent]
        self.objs=rpc_exec(self.model,"read",self.obj_ids,self.tree.field_names)
        self.tree.set_vals(self.objs)

    def draw(self,win):
        self.root_list.draw(win)
        self.tree.draw(win)

class FormWindow(DeckPanel):
    def __init__(self):
        super(FormWindow,self).__init__()
        self.tree=ListView()
        self.form=Form()
        self.add(self.tree)
        self.add(self.form)

    def parse_tree(self,el,fields):
        if el.tag=="tree":
            wg=Listview()
            for child in el:
                headers=[]
                if child.tag=="field":
                    name=child.attrib["name"]
                    field=fields[name]
                    headers.append((name,field["string"]))
                wg.headers=headers
        return wg

    def parse_form(self,el,panel=None,fields=None):
        if el.tag=="form":
            wg=Form()
            wg.borders=[1,1,1,1]
            for child in el:
                self.parse_form(child,panel=wg,fields=fields)
            return wg
        elif el.tag=="tree":
            wg=ListView()
            for child in el:
                name=child.attrib["name"]
                field=fields[name]
                wg.headers.append((name,field["string"]))
            return wg
        elif el.tag=="label":
            wg=Label()
            wg.set_view_attrs(el.attrib)
            panel.add(wg)
            return wg
        elif el.tag=="newline":
            panel.newline()
            return None
        elif el.tag=="separator":
            wg=Separator()
            wg.set_view_attrs(el.attrib)
            panel.add(wg)
            return wg
        elif el.tag=="button":
            wg=Button()
            wg.set_view_attrs(el.attrib)
            panel.add(wg)
            return wg
        elif el.tag=="field":
            field=fields[el.attrib["name"]]
            if not el.attrib.get("nolabel"):
                wg_l=FieldLabel()
                wg_l.set_field_attrs(field)
                wg_l.set_view_attrs(el.attrib)
                panel.add(wg_l)
            if field["type"]=="char":
                wg=InputChar()
            elif field["type"]=="integer":
                wg=InputInteger()
            elif field["type"]=="float":
                wg=InputFloat()
            elif field["type"]=="boolean":
                wg=InputBoolean()
            elif field["type"]=="date":
                wg=InputDate()
            elif field["type"]=="datetime":
                wg=InputDatetime()
            elif field["type"]=="text":
                wg=InputText()
            elif field["type"]=="selection":
                wg=InputSelect()
                wg.set_selection(field["selection"])
            elif field["type"]=="many2one":
                wg=InputM2O()
            elif field["type"]=="one2many":
                wg=InputO2M()
                tree_view=field["views"].get("tree")
                if not tree_view:
                    tree_view=rpc_exec(field["relation"],"fields_view_get",False,"tree",{})
                tree_arch=xml.etree.ElementTree.fromstring(tree_view["arch"])
                wg_t=self.parse_form(tree_arch,fields=tree_view["fields"])
                wg_t.relation=field["relation"]
                wg.add(wg_t,"tree")
                form_view=field["views"].get("form")
                if not form_view:
                    form_view=rpc_exec(field["relation"],"fields_view_get",False,"form",{})
                form_arch=xml.etree.ElementTree.fromstring(form_view["arch"])
                wg_f=self.parse_form(form_arch,fields=form_view["fields"])
                wg_f.relation=field["relation"]
                wg.add(wg_f,"form")
            elif field["type"]=="many2many":
                wg=InputM2M()
                tree_view=field["views"].get("tree")
                if not tree_view:
                    tree_view=rpc_exec(field["relation"],"fields_view_get",False,"tree",{})
                tree_arch=xml.etree.ElementTree.fromstring(tree_view["arch"])
                wg_t=self.parse_form(tree_arch,fields=tree_view["fields"])
                wg_t.relation=field["relation"]
                wg.add(wg_t)
            else:
                raise Exception("unsupported field type: %s"%field["type"])
            wg.name=el.attrib["name"]
            wg.set_field_attrs(field)
            wg.set_view_attrs(el.attrib)
            panel.add(wg)
            return wg
        elif el.tag=="group":
            wg=Group()
            wg.set_view_attrs(el.attrib)
            for child in el:
                self.parse_form(child,wg,fields=fields)
            panel.add(wg)
            return wg
        elif el.tag=="notebook":
            wg=Notebook()
            wg.set_view_attrs(el.attrib)
            wg.borders=[1,1,1,1]
            for elp in el:
                wg_p=Page()
                wg_p.set_view_attrs(elp.attrib)
                wg.add(wg_p)
                for child in elp:
                    self.parse_form(child,wg_p,fields=fields)
            panel.add(wg)
            return wg
        else:
            raise Exception("invalid tag: "+el.tag)

    def load_view(self):
        if self.mode=="tree":
            self.tree_view=rpc_exec(self.relation,"fields_view_get",None,"tree",self.context)
            self.tree_arch=xml.etree.ElementTree.fromstring(self.view["arch"])
            self.tree=self.parse_tree(self.tree_arch,self.tree_view["fields"])
        elif self.mode=="form":
            self.form_view=rpc_exec(self.relation,"fields_view_get",None,"form",self.context)
            self.form_fields=self.view["fields"]
            self.form_arch=xml.etree.ElementTree.fromstring(self.view["arch"])
            self.form=self.parse_form(self.form_arch,self.form_view["fields"])

    def load_data(self):
        if self.mode=="tree":
            self.obj_ids=rpc_exec(self.relation,"search",self.domain)
            self.objs=rpc_exec(self.relation,"read",self.obj_ids,self.tree_fields.keys())
            self.tree.set_vals(self.objs)
        elif self.mode=="form":
            self.obj=rpc_exec(self.relation,"read",[self.obj_id],self.form_fields.keys())[0]
            self.form.set_vals(self.obj)

class TabPanel(DeckPanel):
    def __init__(self):
        super(TabPanel,self).__init__()
        self.can_focus=True

    def draw(self,win):
        x=self.x
        i=0
        for wg in self._childs:
            s="%d %s "%(i+1,wg.name)
            if wg==self.cur_wg:
                win.addstr(self.y,x,s,curses.A_REVERSE)
            else:
                win.addstr(self.y,x,s)
            i+=1
            x+=len(s)
        for wg in self._childs:
            wg.draw(win)

def view_to_s(el,d=0):
    s="  "*d+el.tag
    for k in sorted(el.attrib.keys()):
        v=el.attrib[k]
        s+=" %s=%s"%(k,v)
    for child in el:
        s+="\n"+view_to_s(child,d+1)
    return s

def act_window_tree(act):
    win=TreeWindow()
    win.model=act["res_model"]
    win.domain=act["domain"] and eval(act["domain"]) or []
    win.context=act["context"] and eval(act["context"]) or {}
    win.view_id=act["view_id"][0]
    win.name=act["name"]
    win.load_view()
    win.load_data()
    tab_panel.add(win)
    tab_panel.compute(80,0,0)
    tab_panel.draw(screen)
    tab_panel.set_focus()
    screen.refresh()

def act_window_form(act):
    win=FormWindow()
    win.model=act["res_model"]
    win.domain=act["domain"] and eval(act["domain"]) or []
    win.context=act["context"] and eval(act["context"]) or {}
    win.load_view()
    win.load_data()
    tab_panel.add(win)
    tab_panel.compute(80,0,0)
    tab_panel.draw(screen)
    tab_panel.set_focus()
    screen.refresh()

def act_window(act_id):
    #log("act_window",act_id)
    act=rpc_exec("ir.actions.act_window","read",act_id,["name","res_model","domain","view_type","view_mode","view_id","context"])
    if act["view_type"]=="tree":
        act_window_tree(act)
    elif act["view_type"]=="form":
        act_window_form(act)
    else:
        raise Exception("Unsupported view type: %s"%act["view_type"])

def action(act_id):
    #log("action",act_id)
    act=rpc_exec("ir.actions.actions","read",act_id,["name","type"])
    if act["type"]=="ir.actions.act_window":
        act_window(act_id)
    else:
        raise Exception("Unsupported action type: %s"%act["type"])

def start(stdscr):
    global screen,tab_panel
    screen=stdscr
    screen.keypad(1)
    tab_panel=TabPanel()
    user=rpc_exec("res.users","read",uid,["name","action_id","menu_id"])
    action(user["action_id"][0])
    while 1:
        k=screen.getch()
        tab_panel.key_pressed(k)

curses.wrapper(start)
