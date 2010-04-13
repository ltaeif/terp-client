#!/usr/bin/python
##############################################################################
#
#    OpenERP-Text: Text-Mode Client for OpenERP
#    Copyright (C) 2010 David Janssens (david.j@almacom.co.th)
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

import curses
import curses.textpad
import curses.panel
import sys
import time
import xmlrpclib
import xml.etree.ElementTree
import pdb
import socket
import traceback

def ex_info(type,value,tb):
    traceback.print_exception(type,value,tb)
    pdb.pm()
sys.excepthook=ex_info

try:
    host=sys.argv[1]
    dbname=sys.argv[2]
    uid=int(sys.argv[3])
    passwd=sys.argv[4]
    try:
        debug=sys.argv[5]
    except:
        debug=False
except:
    raise Exception("Usage: %s HOST DBNAME UID PASSWD DEBUG"%sys.argv[0])

port=8069
rpc=xmlrpclib.ServerProxy("http://%s:%d/xmlrpc/object"%(host,port))

class Rdb(pdb.Pdb):
    def __init__(self):
        self.old_stdout=sys.stdout
        self.old_stdin=sys.stdin
        self.sock_s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        self.sock_s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.sock_s.bind(("",4444))
        self.sock_s.listen(1)
        (sock_c,addr)=self.sock_s.accept()
        sock_f=sock_c.makefile("rw")
        pdb.Pdb.__init__(self,stdin=sock_f,stdout=sock_f)

    def do_continue(self,arg):
        sys.stdout=self.old_stdout
        sys.stdin=self.old_stdin
        self.sock_s.close()
        self.set_continue()
        return 1

    do_c=do_cont=do_continue

if debug:
    rdb=Rdb()
else:
    rdb=None

screen=None

def log(*args):
    msg=" ".join([str(a) for a in args])
    screen.addstr(msg+"\n")
    screen.refresh()

def rpc_exec(*args):
    try:
        return rpc.execute(dbname,uid,passwd,*args)
    except Exception,e:
        raise Exception("RPC failed: %s\n%s"%(str(args),str(e)))

class layout_region(object):
    def __init__(self,colspan=4,maxw=-1,name="N/A",h=1,align="left"):
        self.name=name
        self.cy=None
        self.cx=None
        self.colspan=colspan
        self.maxw=maxw
        self.x=None
        self.y=None
        self.w=None
        self.h=h
        self.is_container=False
        self.align=align

    def to_s(self,d=0):
        return "  "*d+"name=%s cy=%s cx=%s colspan=%s maxw=%s h=%s w=%s y=%s x=%s"%(self.name,self.cy,self.cx,self.colspan,self.maxw,self.h,self.w,self.y,self.x)

class layout_container(layout_region):
    def __init__(self,colspan=4,col=4,name="N/A",borders=[0,0,0,0],seps=[0,1]):
        super(layout_container,self).__init__(colspan,-1,name,h=None)
        self.is_container=True
        self.num_cols=col
        self.num_rows=0
        self.widths=[]
        self.heights=[]
        self.childs=[]
        self.child_cx=0
        self.child_cy=0
        self.borders=borders
        self.seps=seps
        self.h_top=None
        self.w_left=None

    def add_child(self,el):
        if el.colspan>self.num_cols:
            raise Exception("invalid colspan")
        if self.child_cx+el.colspan>self.num_cols:
            self.child_cy+=1
            self.child_cx=0
        el.cy=self.child_cy
        el.cx=self.child_cx
        self.child_cx+=el.colspan
        self.childs.append(el)
        self.num_rows=el.cy+1

    def newline(self):
        self.child_cy+=1
        self.child_cx=0

    def set_insert_pos(self,cx,cy):
        self.child_cx=cx
        self.child_cy=cy

    def _compute_pass1(self):
        if not self.childs:
            return
        for el in self.childs:
            if el.is_container:
                el._compute_pass1()
        # 1. compute container max width
        expand=False
        for el in self.childs:
            if el.maxw==-1:
                expand=True
                break
        if expand:
            self.maxw=-1
        else:
            w_left=[0]
            for i in range(1,self.num_cols+1):
                w_max=w_left[i-1]
                for el in self.childs:
                    cr=el.cx+el.colspan
                    if cr!=i:
                        continue
                    w=w_left[el.cx]+el.maxw
                    if el.cx>0:
                        w+=self.seps[1]
                    if w>w_max:
                        w_max=w
                w_left.append(w_max)
            self.maxw=self.borders[3]+self.borders[1]+w_left[-1]
        # 2. compute container height
        self.h_top=[0]
        for i in range(self.num_rows):
            h=0
            for el in self.childs:
                if el.cy!=i:
                    continue
                if el.h>h:
                    h=el.h
            h+=self.h_top[-1]
            if i>0:
                h+=self.seps[0]
            self.h_top.append(h)
        self.h=self.borders[0]+self.h_top[-1]+self.borders[2]

    def _compute_pass2(self):
        if not self.childs:
            self.w=0
            return
        # 1. compute child widths
        w_avail=self.w-self.borders[3]-self.borders[1]
        for el in self.childs:
            el.w=0
        w_left=[0]*(self.num_cols+1)
        w_rest=w_avail
        # allocate space fairly to every child
        while w_rest>0:
            w_alloc=w_rest-self.seps[1]*(self.num_cols-1)
            if w_alloc>self.num_cols:
                dw=w_alloc/self.num_cols
            else:
                dw=1
            incr=False
            for el in self.childs:
                if el.maxw!=-1:
                    if not el.w<el.maxw:
                        continue
                    dw_=min(dw,el.maxw-el.w)
                else:
                    dw_=dw
                el.w+=dw_
                incr=True
                w=w_left[el.cx]+el.w
                if el.cx>0:
                    w+=self.seps[1]
                cr=el.cx+el.colspan
                if w>w_left[cr]:
                    dwl=w-w_left[cr]
                    for i in range(cr,self.num_cols+1):
                        w_left[i]+=dwl
                    w_rest=w_avail-w_left[-1]
                    if w_rest==0:
                        break
            if not incr:
                break
        self.w_left=w_left
        # add extra cell space to regions
        for el in self.childs:
            if el.maxw!=-1 and el.w==el.maxw:
                continue
            w=w_left[el.cx]+el.w
            if el.cx>0:
                w+=self.seps[1]
            cr=el.cx+el.colspan
            if w<w_left[cr]:
                dw=w_left[cr]-w
                if el.maxw!=-1:
                    dw=min(dw,el.maxw-el.w)
                el.w+=dw
        # 2. compute child positions
        for el in self.childs:
            el.y=self.y+self.borders[0]+self.h_top[el.cy]+(el.cy>0 and self.seps[0] or 0)
            if el.align=="right":
                el.x=self.x+self.borders[3]+w_left[el.cx+el.colspan]-el.w
            else:
                el.x=self.x+self.borders[3]+w_left[el.cx]+(el.cx>0 and self.seps[1] or 0)
        for el in self.childs:
            if el.is_container:
                el._compute_pass2()

    def compute(self,w,x,y):
        self._compute_pass1()
        self.w=w
        self.x=x
        self.y=y
        self._compute_pass2()

    def to_s(self,d=0):
        s=super(layout_container,self).to_s(d)+" num_cols=%s num_rows=%s h_top=%s w_left=%s"%(self.num_cols,self.num_rows,str(self.h_top),str(self.w_left))
        for el in self.childs:
            s+="\n"+el.to_s(d+1)
        return s

class wigdet(object):
    def __init__(self):
        self.region=None
        self.value=None

    def process_key():
        pass

class container_widget(widget):
    def __init__(self):
        self.childs=[]

    def add_child(widget):
        self.childs.append(widget)

class table(container_widget):
    def __init__(self):
        pass

class input_widget(widget):
    def __init__(self):
        self.value=None

class label(widget):
    def __init__(self):
        pass

class button(widget):
    def __init__(self):
        pass

class separator(widget):
    def __init__(self):
        pass

class field(input_widget):
    def __init__(self):
        pass

class char_field(field):
    def __init__(self):
        pass

class integer_field(field):
    def __init__(self):
        pass

class float_field(field):
    def __init__(self):
        pass

class select_field(field):
    def __init__(self):
        pass

class text_field(field):
    def __init__(self):
        pass

class m2o_field(field):
    def __init__(self):
        pass

class o2m_field(field,container_widget):
    def __init__(self):
        pass

class m2m_field(field,container_widget):
    def __init__(self):
        pass

class group(container_widget):
    def __init__(self):
        pass

class notebook(container_widget):
    def __init__(self):
        pass

class form(container_widget):
    def __init__(self):
        pass

class listbox(container_widget):
    def __init__(self):
        pass

class window(container_widget):
    def __init__(self):
        pass

class tree_view(window):
    def __init__(self):
        pass

class form_view(window):
    def __init__(self):
        pass

class screen(container_widget):
    def __init__(self):
        pass

def val_to_s(val,field):
    if val==None or val==False:
        return ""
    if field["type"]=="many2one":
        return val[1]
    elif field["type"]=="selection":
        for k,v in field["selection"]:
            if k==val:
                return v
        raise Exception("invalid selection: %s"%k)
    else:
        return str(val)

def set_view_regions(el,parent=None,objs=[]):
    el.parent=parent
    for child in el:
        set_view_regions(child,parent=el,objs=objs)

    if el.tag=="form":
        colspan=int(el.attrib.get("colspan",1))
        col=int(el.attrib.get("col",4))
        el.region=layout_container(colspan=colspan,col=col,name="form",borders=[1,1,1,1])
    elif el.tag=="tree":
        colspan=1
        col=len(el)
        el.region=layout_container(colspan=colspan,col=col,name="tree",borders=[1,1,1,1])
    elif el.tag=="label":
        colspan=int(el.attrib.get("colspan",1))
        maxw=len(el.attrib.get("string",""))
        el.region=layout_region(colspan,maxw,"label")
    elif el.tag=="separator":
        colspan=int(el.attrib.get("colspan",1))
        maxw=-1
        el.region=layout_region(colspan,maxw,"separator")
    elif el.tag=="button":
        states=el.attrib.get("states")
        if not states or "draft" in states:
            colspan=int(el.attrib.get("colspan",1))
            maxw=len(el.attrib.get("string",""))+2
            el.region=layout_region(colspan,maxw,"button")
        else:
            el.region=None
            el.attrib["invisible"]=True
    elif el.tag=="newline":
        el.region=None
    elif el.tag=="field":
        if parent.tag=="tree":
            el.region=layout_container(colspan=1,col=1,name="field_col")
            maxw_label=len(el.field.get("string",""))
            if parent.parent:
                h=1
            else:
                h=2
            el.region_label=layout_region(1,maxw_label,"field_label",h=h)
            el.region.add_child(el.region_label)
            el.lines=[]
            for obj in objs:
                val=obj[el.attrib["name"]]
                s=val_to_s(val,el.field)
                r=layout_region(1,len(s),"field_line")
                el.region.add_child(r)
                el.lines.append({"region":r,"obj":obj})
        else:
            colspan=int(el.attrib.get("colspan",2))
            if el.attrib.get("nolabel"):
                el.region_label=None
                colspan_label=0
            else:
                maxw_label=len(el.field.get("string",""))+1
                colspan_label=1
                el.region_label=layout_region(colspan_label,maxw_label,"field_label",align="right")
            colspan_input=colspan-colspan_label
            if el.field["type"] in ("one2many","many2many"):
                h_input=8
                maxw_input=-1
            else:
                h_input=1
                if el.field.get("readonly"):
                    maxw_input=len(val_to_s(el.value,el.field))
                else:
                    maxw_input=-1
            el.region_input=layout_region(colspan_input,maxw_input,el.attrib["name"],h=h_input)
            el.region=None
    elif el.tag=="group":
        colspan=int(el.attrib.get("colspan",2))
        col=int(el.attrib.get("col",4))
        el.region=layout_container(colspan,col,"group")
    elif el.tag=="notebook":
        colspan=int(el.attrib.get("colspan",2))
        el.region=layout_container(colspan,1,"notebook",borders=[1,1,1,1])
    elif el.tag=="page":
        colspan=int(el.attrib.get("colspan",1))
        col=int(el.attrib.get("col",4))
        el.region=layout_container(colspan,col,"page")
    else:
        raise Exception("invalid tag: "+el.tag)

    page_no=0
    for child in el:
        if child.tag=="newline":
            el.region.newline()
        elif child.tag=="field":
            if el.tag=="tree":
                el.region.add_child(child.region)
            else:
                if child.region_label:
                    el.region.add_child(child.region_label)
                el.region.add_child(child.region_input)
        elif child.tag=="page":
            if page_no!=0:
                child.attrib["invisible"]=True
            el.region.set_insert_pos(0,0)
            el.region.add_child(child.region)
            page_no+=1
        else:
            if child.region:
                el.region.add_child(child.region)
    return el.region

def draw_view(win,el,h=None):
    if el.attrib.get("invisible"):
        return []
    if el.tag=="form":
        r=el.region
        curses.textpad.rectangle(win,r.y,r.x,r.y+r.h-1,r.x+r.w-1)
    elif el.tag=="tree":
        r=el.region
        curses.textpad.rectangle(win,r.y,r.x,r.y+h-1,r.x+r.w-1)
        i=0
        for child in el:
            rl=child.region_label
            s=child.field["string"][:rl.w]
            win.addstr(rl.y,rl.x,s)
            rc=child.region
            if i>0:
                win.vline(r.y+1,rc.x-1,curses.ACS_VLINE,h-2)
                win.addch(r.y,rc.x-1,curses.ACS_TTEE)
                win.addch(r.y+h-1,rc.x-1,curses.ACS_BTEE)
            i+=1
        if not el.parent:
            win.hline(r.y+2,r.x+1,curses.ACS_HLINE,r.w-2)
            win.addch(r.y+2,r.x,curses.ACS_LTEE)
            win.addch(r.y+2,r.x+r.w-1,curses.ACS_RTEE)
            i=0
            for child in el:
                if i>0:
                    rc=child.region
                    win.addch(r.y+2,rc.x-1,curses.ACS_PLUS)
                i+=1
        for child in el:
            name=child.attrib["name"]
            for line in child.lines:
                r=line["region"]
                obj=line["obj"]
                s=val_to_s(obj[name],child.field)
                s=s[:r.w]
                win.addstr(r.y,r.x,s)
        return []
    elif el.tag=="label":
        r=el.region
        s=el.attrib.get("string","")[:r.w]
        win.addstr(r.y,r.x,s)
    elif el.tag=="separator":
        r=el.region
        win.hline(r.y,r.x,curses.ACS_HLINE,r.w)
        s=el.attrib.get("string","")
        win.addstr(r.y,r.x+2,s)
    elif el.tag=="button":
        r=el.region
        s="["+el.attrib.get("string","")[:r.w-2]+"]"
        win.addstr(r.y,r.x,s)
    elif el.tag=="field":
        if el.region_label:
            r=el.region_label
            s=el.field["string"]
            s=s[:r.w-1]+":"
            win.addstr(r.y,r.x,s)
        r=el.region_input
        if el.field["type"] not in ("one2many","many2many"):
            s=val_to_s(el.value,el.field)
            s=s[:r.w]
            if el.field.get("readonly"):
                if s:
                    win.addstr(r.y,r.x,s)
            else:
                if len(s)<r.w:
                    s+=" "*(r.w-len(s))
                win.addstr(r.y,r.x,s,curses.A_UNDERLINE)
        else:
            return [el]
    elif el.tag=="group":
        pass
    elif el.tag=="notebook":
        r=el.region
        curses.textpad.rectangle(win,r.y,r.x,r.y+r.h-1,r.x+r.w-1)
        x=r.x+1
        i=0
        for page in el:
            if i==0:
                win.addch(r.y,x,curses.ACS_RTEE)
            else:
                win.addch(r.y,x,curses.ACS_VLINE)
            x+=1
            s=page.attrib["string"]
            if page.attrib.get("invisible"):
                win.addstr(r.y,x," "+s+" ")
            else:
                win.addstr(r.y,x," "+s+" ",curses.A_BOLD)
            x+=len(s)+2
            i+=1
        win.addch(r.y,x,curses.ACS_LTEE)
    elif el.tag=="page":
        pass
    res=[]
    for child in el:
        todo=draw_view(win,child)
        res+=todo
    return res

def view_to_s(el,d=0):
    s="  "*d+el.tag
    for k in sorted(el.attrib.keys()):
        v=el.attrib[k]
        s+=" %s=%s"%(k,v)
    for child in el:
        s+="\n"+view_to_s(child,d+1)
    return s

def act_window_tree(act):
    #log("act_window_tree",act)
    model=act["res_model"]
    domain=act["domain"] and eval(act["domain"]) or []
    context=act["context"] and eval(act["context"]) or {}
    view=rpc_exec(model,"fields_view_get",act["view_id"][0],"tree",context)
    #log("view",view)
    ids=rpc_exec(model,"search",domain)
    objs_l=rpc_exec(model,"read",ids,["id","name"])
    screen.addstr(0,0,"1 "+act["name"])
    screen.chgat(0,0,7,curses.A_REVERSE)
    win=screen.subwin(23,80,1,0)
    win.clear()
    win.box()
    win.vline(1,25,curses.ACS_VLINE,21)
    win.addch(0,25,curses.ACS_TTEE)
    win.addch(22,25,curses.ACS_BTEE)
    win.hline(2,26,curses.ACS_HLINE,78)
    win.addch(2,25,curses.ACS_LTEE)
    win.addch(2,79,curses.ACS_RTEE)
    win_l=win.subwin(21,24,2,1)
    win_r=win.subwin(19,53,4,26)
    pad_r=curses.newpad(100,53)
    y=0
    for obj in objs_l:
        win_l.addstr(y,1,obj["name"])
        y+=1
    fields=view["fields"]
    field_names=fields.keys()
    field_parent=view["field_parent"]
    win.addstr(1,27,fields[field_names[0]]["string"])
    if objs_l:
        child_ids=rpc_exec(model,"read",objs_l[0]["id"],[field_parent])[field_parent]
        objs_r=rpc_exec(model,"read",child_ids,["id",field_parent]+field_names)
        y=0
        for obj in objs_r:
            obj["_depth"]=0
            obj["_expanded"]=False
            pad_r.addstr(y,1,obj["name"])
            if obj[field_parent]:
                pad_r.addch(y,0,"/")
            y+=1
    select_l=0
    win_l.chgat(select_l,0,24,curses.A_REVERSE)
    screen.refresh()
    pad_r.refresh(0,0,4,26,22,78)
    screen.move(2,2)
    mode="l"
    scroll_r=0
    while 1:
        c=screen.getch()
        if c==curses.KEY_DOWN:
            if mode=="l":
                i=screen.getyx()[0]-2
                i+=1
                if i>=len(objs_l):
                    i=0
                screen.move(i+2,2)
            elif mode=="r":
                i=screen.getyx()[0]-4+scroll_r
                i+=1
                if i>=len(objs_r):
                    i=0
                obj=objs_r[i]
                scroll=False
                if i-scroll_r>18:
                    scroll_r=i-18
                    scroll=True
                elif i<scroll_r:
                    scroll_r=i
                    scroll=True
                if scroll:
                    pad_r.refresh(scroll_r,0,4,26,22,79)
                screen.move(4+i-scroll_r,27+obj["_depth"]*2)
        elif c==curses.KEY_UP:
            if mode=="l":
                i=screen.getyx()[0]-2
                i-=1
                if i<0:
                    i=len(objs_l)-1
                screen.move(i+2,2)
            elif mode=="r":
                i=screen.getyx()[0]-4+scroll_r
                i-=1
                if i<0:
                    i=len(objs_r)-1
                obj=objs_r[i]
                scroll=False
                if i-scroll_r>18:
                    scroll_r=i-18
                    scroll=True
                elif i<scroll_r:
                    scroll_r=i
                    scroll=True
                if scroll:
                    pad_r.refresh(scroll_r,0,4,26,22,79)
                screen.move(i+4-scroll_r,27+obj["_depth"]*2)
        elif c==curses.KEY_RIGHT:
            if mode=="l":
                mode="r"
                screen.move(4,27)
            elif mode=="r":
                y,x=screen.getyx()
                i=y-4
                obj=objs_r[i]
                if obj["_expanded"]:
                    continue
                child_ids=rpc_exec(model,"read",obj["id"],[field_parent])[field_parent]
                if child_ids:
                    childs=rpc_exec(model,"read",child_ids,["id",field_parent]+field_names)
                    childs.reverse()
                    for child in childs:
                        child["_depth"]=obj["_depth"]+1
                        child["_expanded"]=False
                        objs_r.insert(i+1,child)
                        pad_r.move(i+1,0)
                        pad_r.insertln()
                        pad_r.addstr(i+1,1+child["_depth"]*2,child["name"])
                        if child[field_parent]:
                            pad_r.addch(i+1,child["_depth"]*2,"/")
                    obj["_expanded"]=True
                pad_r.refresh(0,0,4,26,22,79)
                screen.move(y,x)
        elif c==curses.KEY_LEFT:
            if mode=="r":
                i=screen.getyx()[0]-4+scroll_r
                obj=objs_r[i]
                if obj["_depth"]==0 and not obj["_expanded"]:
                    mode="l"
                    screen.move(2+select_l,2)
                    win_l.refresh()
                    continue
                while not obj["_expanded"]:
                    i-=1
                    obj=objs_r[i]
                child_ids=obj[field_parent]
                while i+1<len(objs_r):
                    child=objs_r[i+1]
                    if child["id"] not in child_ids:
                        break
                    child_ids+=child[field_parent]
                    objs_r.pop(i+1)
                    pad_r.move(i+1,0)
                    pad_r.deleteln()
                    folded=True
                pad_r.refresh(0,0,4,26,22,79)
                screen.move(i+4,27+obj["_depth"]*2)
                obj["_expanded"]=False
        elif c==ord("\t"):
            if mode=="l":
                mode="r"
                screen.move(4,27)
            elif mode=="r":
                mode="l"
                screen.move(2+select_l,2)
        elif c==ord("\n"):
            if mode=="l":
                y,x=screen.getyx()
                win_l.chgat(select_l,0,24,0)
                select_l=y-2
                win_l.chgat(select_l,0,24,curses.A_REVERSE)
                win_l.refresh()

                pad_r.clear()
                child_ids=rpc_exec(model,"read",objs_l[select_l]["id"],[field_parent])[field_parent]
                objs_r=rpc_exec(model,"read",child_ids,["id",field_parent]+field_names)
                i=0
                for obj in objs_r:
                    obj["_depth"]=0
                    obj["_expanded"]=False
                    pad_r.addstr(i,1,obj["name"])
                    if obj[field_parent]:
                        pad_r.addch(i,0,"/")
                    i+=1
                pad_r.refresh(0,0,4,26,22,78)
                screen.move(y,x)
            elif mode=="r":
                i=screen.getyx()[0]-4+scroll_r
                obj=objs_r[i]
                res=rpc_exec("ir.values","get","action","tree_but_open",[(model,obj["id"])])
                if not res:
                    continue
                act=res[0][2]
                action(act["id"])

def act_window_form(act):
    model=act["res_model"]
    view_modes=act["view_mode"].split(",")
    mode=view_modes[0]
    domain=act["domain"] and eval(act["domain"]) or []
    context=act["context"] and eval(act["context"]) or {}
    view_id=False
    view=rpc_exec(model,"fields_view_get",view_id,mode,context)
    fields=view["fields"]
    field_names=fields.keys()
    arch=xml.etree.ElementTree.fromstring(view["arch"])
    for el in arch.getiterator("field"):
        el.field=fields[el.attrib["name"]]
    ids=rpc_exec(model,"search",domain)
    objs=rpc_exec(model,"read",ids,["id"]+field_names)
    screen.clear()
    screen.addstr("1 Menu ")
    screen.addstr("2 "+act["name"]+" ",curses.A_REVERSE)
    pad=curses.newpad(100,80)
    if mode=="tree":
        set_view_regions(arch,objs=objs)
        arch.region.compute(80,0,0)
        draw_view(pad,arch,23)
        screen.refresh()
        pad.refresh(0,0,1,0,23,80)
        screen.move(4,1)
    elif mode=="form":
        defaults=rpc_exec(model,"default_get",field_names)
        state=None
        for el in arch.getiterator("field"):
            val=defaults.get(el.attrib["name"])
            if not val:
                el.value=val
                continue
            if el.field["type"]=="many2one":
                id,name=rpc_exec(el.field["relation"],"name_get",[val])[0]
                el.value=(id,name)
            else:
                el.value=val
            if el.attrib["name"]=="state":
                state=el.value
        for el in arch.getiterator("field"):
            states=el.field.get("states")
            if not states:
                continue
            vals=states.get(state)
            if not vals:
                continue
            for k,v in vals:
                el.field[k]=v
        set_view_regions(arch)
        arch.region.compute(80,0,0)
        todo=draw_view(pad,arch)
        screen.refresh()
        pad.refresh(0,0,1,0,23,80)
        for elf in todo:
            view=elf.field["views"]["tree"]
            et=xml.etree.ElementTree.fromstring(view["arch"])
            view["et"]=et
            for el in et.getiterator("field"):
                el.field=view["fields"][el.attrib["name"]]
            set_view_regions(et,elf)
            r=elf.region_input
            rf=et.region
            rf.compute(r.w,0,0)
            padf=curses.newpad(rf.h+10,rf.w+10)
            draw_view(padf,et,r.h)
            padf.refresh(0,0,r.y+1,r.x,r.y+r.h,r.x+r.w-1)
        fld=arch.find(".//field")
        if fld!=None:
            r=fld.region_input
            screen.move(1+r.y,r.x)
    else:
        raise Exception("view mode not implemented: "+mode)
    while 1:
        c=screen.getch()
        rdb.set_trace()
        if c==curses.KEY_DOWN:
            y,x=screen.getyx()
            i=y-4
            i+=1
            if i>len(objs)-1:
                i=0
            screen.move(4+i,1)
        elif c==curses.KEY_UP:
            y,x=screen.getyx()
            i=y-4
            i-=1
            if i<0:
                i=len(objs)-1
            screen.move(4+i,1)
        elif c==ord(" "):
            y,x=screen.getyx()
            i=y-4
            obj=objs[i]
            if not obj.get("_selected"):
                x=1
                for name in headers:
                    screen.chgat(y,x,colw[name],curses.A_REVERSE)
                    x+=colw[name]+1
                obj["_selected"]=True
            else:
                x=1
                for name in headers:
                    screen.chgat(y,x,colw[name],0)
                    x+=colw[name]+1
                obj["_selected"]=False
            screen.refresh()
        elif c==ord("\n"):
            pass

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
    global screen
    screen=stdscr
    screen.keypad(1)
    #curses.init_pair(1,curses.COLOR_RED,curses.COLOR_BLACK)
    user=rpc_exec("res.users","read",uid,["name","action_id","menu_id"])
    action(user["action_id"][0])
curses.wrapper(start)
