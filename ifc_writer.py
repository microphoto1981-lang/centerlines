# -*- coding: utf-8 -*-
from pathlib import Path
import base64, uuid, math

def guid():
    b=uuid.uuid4().bytes
    return base64.b64encode(b).decode().replace("+","_").replace("/","$").rstrip("=")[:22]

class IFCWriter:
    def __init__(self):
        self.e=[]; self.n=1
    def add(self,s):
        i=self.n; self.n+=1; self.e.append((i,s)); return i
    def R(self,i): return f"#{i}"
    def p3(self,x,y,z): return self.add(f"IFCCARTESIANPOINT(({x:.6f},{y:.6f},{z:.6f}))")
    def p2(self,x,y): return self.add(f"IFCCARTESIANPOINT(({x:.6f},{y:.6f}))")
    def d3(self,x,y,z): return self.add(f"IFCDIRECTION(({x:.6f},{y:.6f},{z:.6f}))")
    def d2(self,x,y): return self.add(f"IFCDIRECTION(({x:.6f},{y:.6f}))")
    def a3(self,p,z,x): return self.add(f"IFCAXIS2PLACEMENT3D({self.R(p)},{self.R(z)},{self.R(x)})")
    def a2(self,p,x): return self.add(f"IFCAXIS2PLACEMENT2D({self.R(p)},{self.R(x)})")
    def lp(self,parent,axis): return self.add(f"IFCLOCALPLACEMENT({self.R(parent) if parent else '$'},{self.R(axis)})")
    def profile_rect(self,name,w,d):
        return self.add(f"IFCRECTANGLEPROFILEDEF(.AREA.,'{name}',{self.R(self.a2(self.p2(0,0),self.d2(1,0)))},{w:.6f},{d:.6f})")
    def profile_wall(self,length,thickness):
        # IFC RULE (IfcRectangleProfileDef):
        #   the rectangle is ALWAYS centred on its own Position origin, i.e.
        #   it spans [-XDim/2 .. +XDim/2] x [-YDim/2 .. +YDim/2].
        #
        # The wall LocalPlacement origin is the real axis start point A and
        # the local X axis points from A to B. Therefore a profile positioned
        # at (0,0) would make the wall run from A-L/2 to A+L/2 - the wall
        # would be built around the MIDPOINT of A-B. That is the source of the
        # horizontal wall offset (L-junction turning into a cross).
        #
        # Fix: shift the profile position by +L/2 along the local X axis only.
        # Result:
        #   local X : 0 .. L        -> length starts exactly at A, ends at B
        #   local Y : -T/2 .. +T/2  -> thickness stays symmetric about the axis
        # No offset is applied across the axis, and the point order A->B is
        # never changed.
        pos = self.a2(self.p2(length/2.0,0.0),self.d2(1,0))
        return self.add(
            f"IFCRECTANGLEPROFILEDEF(.AREA.,'SCADPARAMPROF_WALL',"
            f"{self.R(pos)},{length:.6f},{thickness:.6f})"
        )

    def profile_poly(self,pts):
        refs=[self.R(self.p2(x,y)) for x,y in pts]
        if refs[0]!=refs[-1]: refs.append(refs[0])
        pl=self.add(f"IFCPOLYLINE(({','.join(refs)}))")
        return self.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{self.R(pl)})")
    def shape(self,solid,kind="SweptSolid"):
        rep=self.add(f"IFCSHAPEREPRESENTATION({self.R(self.ctx)},'Body','{kind}',({self.R(solid)}))")
        return self.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({self.R(rep)}))")
    def solid(self,profile,h,zaxis,origin):
        ax=self.a3(origin,self.d3(0,0,1),self.d3(1,0,0))
        return self.add(f"IFCEXTRUDEDAREASOLID({self.R(profile)},{self.R(ax)},{self.R(zaxis)},{h:.6f})")
    def init(self):
        org=self.add("IFCORGANIZATION($,'CENTERLINES',$,$,$)")
        app=self.add(f"IFCAPPLICATION({self.R(org)},'1.0','CENTERLINES','CENTERLINES')")
        person=self.add("IFCPERSON('','','',$,$,$,$,$)")
        po=self.add(f"IFCPERSONANDORGANIZATION({self.R(person)},{self.R(org)},$)")
        own=self.add(f"IFCOWNERHISTORY({self.R(po)},{self.R(app)},$,.NOCHANGE.,$,$,$,0)")
        metre=self.add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
        rad=self.add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)")
        units=self.add(f"IFCUNITASSIGNMENT(({self.R(metre)},{self.R(rad)}))")
        o=self.p3(0,0,0); z=self.d3(0,0,1); x=self.d3(1,0,0); ax=self.a3(o,z,x)
        self.ctx=self.add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-006,{self.R(ax)},$)")
        proj=self.add(f"IFCPROJECT('{guid()}',{self.R(own)},'CENTERLINES','',$,$,$,({self.R(self.ctx)}),{self.R(units)})")
        site_lp=self.lp(None,ax); site=self.add(f"IFCSITE('{guid()}',{self.R(own)},'Site',$,$,{self.R(site_lp)},$,$,.ELEMENT.,$,$,0.,$,$)")
        b_lp=self.lp(site_lp,ax); bld=self.add(f"IFCBUILDING('{guid()}',{self.R(own)},'Building',$,$,{self.R(b_lp)},$,$,.ELEMENT.,$,$,$)")
        self.owner=own; self.building=bld; self.building_lp=b_lp
        # Single shared material for wall layer sets (IfcMaterialLayer.Material).
        self.material=self.add("IFCMATERIAL('Concrete')")
        self.add(f"IFCRELAGGREGATES('{guid()}',{self.R(own)},'SiteContainer','',{self.R(site)},({self.R(bld)}))")
        self.add(f"IFCRELAGGREGATES('{guid()}',{self.R(own)},'ProjectContainer','',{self.R(proj)},({self.R(site)}))")
    def storey(self,f):
        p=self.p3(0,0,f["z"]); ax=self.a3(p,self.d3(0,0,1),self.d3(1,0,0)); lp=self.lp(self.building_lp,ax)
        s=self.add(f"IFCBUILDINGSTOREY('{guid()}',{self.R(self.owner)},{repr(f.get('name') or ('Storey '+str(f['floor_number'])))},$,$,{self.R(lp)},$,$,.ELEMENT.,$)")
        self.add(f"IFCRELAGGREGATES('{guid()}',{self.R(self.owner)},'BuildingContainer','',{self.R(self.building)},({self.R(s)}))")
        return s, lp
    def column(self,c,f,storey_lp):
        w=c.get("width",.4) or .4; d=c.get("depth",.4) or .4; z0=f["z"]; h=max(.001,c.get("z2",z0+3)-c.get("z1",z0))
        prof=self.profile_rect("SCADPARAMPROF_COLUMN",w,d)
        solid=self.solid(prof,h,self.d3(0,0,1),self.p3(0,0,c.get("z1",z0)-z0))
        shp=self.shape(solid)
        loc=self.lp(storey_lp,self.a3(self.p3(c["x"],c["y"],0),self.d3(0,0,1),self.d3(1,0,0)))
        return self.add(f"IFCCOLUMN('{guid()}',{self.R(self.owner)},'Column {c['id']}','',$,{self.R(loc)},{self.R(shp)},'{guid()}',$)")
    def wall(self,w,f,storey_lp):
        x1,y1,x2,y2=w["x1"],w["y1"],w["x2"],w["y2"]

        # CENTERLINES endpoints are authoritative wall-axis endpoints.
        # Preserve their order; wall length runs from endpoint 1 to endpoint 2.
        L=math.hypot(x2-x1,y2-y1)
        if L<1e-9:return None
        t=max(.001,float(w.get("thickness",.2))); z0=f["z"]; h=max(.001,w.get("z2",z0+3)-w.get("z1",z0))
        # profile_wall() puts the rectangle at local X 0..L (start at A),
        # local Y -T/2..+T/2 (thickness centred on the axis).
        # profile_rect() must NOT be used here: it centres the length too.
        prof=self.profile_wall(L,t)
        solid=self.solid(prof,h,self.d3(0,0,1),self.p3(0,0,w.get("z1",z0)-z0))
        # add Axis representation like Forum export
        axline=self.add(f"IFCPOLYLINE(({self.R(self.p2(0,0))},{self.R(self.p2(L,0))}))")
        axisrep=self.add(f"IFCSHAPEREPRESENTATION({self.R(self.ctx)},'Axis','Curve2D',({self.R(axline)}))")
        bodyrep=self.add(f"IFCSHAPEREPRESENTATION({self.R(self.ctx)},'Body','SweptSolid',({self.R(solid)}))")
        shp=self.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({self.R(axisrep)},{self.R(bodyrep)}))")
        ang=math.atan2(y2-y1,x2-x1)
        loc=self.lp(storey_lp,self.a3(self.p3(x1,y1,0),self.d3(0,0,1),self.d3(math.cos(ang),math.sin(ang),0)))
        obj=self.add("IFCWALLSTANDARDCASE('%s',%s,'Wall %s','',$,%s,%s,'%s',$)" % (guid(),self.R(self.owner),w['id'],self.R(loc),self.R(shp),guid()))
        layer=self.add(f"IFCMATERIALLAYER({self.R(self.material)},{t:.6f},.U.,$,$,$,$)")
        ls=self.add(f"IFCMATERIALLAYERSET(({self.R(layer)}),'','')")
        # LayerSetDirection for a wall is .AXIS2. (across the wall = local Y).
        # .AXIS1. means "along the wall length" and makes importers offset the
        # wall along its own axis by OffsetFromReferenceLine.
        # OffsetFromReferenceLine = -T/2 with .POSITIVE. sense gives a layer
        # running -T/2 .. +T/2, i.e. symmetric about the centre line.
        use=self.add(f"IFCMATERIALLAYERSETUSAGE({self.R(ls)},.AXIS2.,.POSITIVE.,{-t/2:.6f},$)")
        self.add(f"IFCRELASSOCIATESMATERIAL('{guid()}',{self.R(self.owner)},$,$,({self.R(obj)}),{self.R(use)})")
        return obj
    def slab(self,p,f,storey_lp):
        pts=p._closed(p.contour); t=float(p.thickness)
        prof=self.profile_poly(pts)
        z0=f["z"]
        solid=self.solid(prof,t,self.d3(0,0,1),self.p3(0,0,p.z-t/2-z0))
        shp=self.shape(solid)
        loc=self.lp(storey_lp,self.a3(self.p3(0,0,0),self.d3(0,0,1),self.d3(1,0,0)))
        return self.add(f"IFCSLAB('{guid()}',{self.R(self.owner)},'Slab {p.id}','',$,{self.R(loc)},{self.R(shp)},'{guid()}',.NOTDEFINED.,$)")
    def write(self,path,floors):
        self.init()
        for f in floors:
            sid, storey_lp=self.storey(f); objs=[]
            for c in f["columns"]:
                q=self.column(c,f,storey_lp)
                if q:objs.append(q)
            for w in f["walls"]:
                q=self.wall(w,f,storey_lp)
                if q:objs.append(q)
            for p in f["plates"]:
                q=self.slab(p,f,storey_lp)
                if q:objs.append(q)
            if objs:
                self.add(f"IFCRELCONTAINEDINSPATIALSTRUCTURE('{guid()}',{self.R(self.owner)},$,$,({','.join(self.R(x) for x in objs)}),{self.R(sid)})")
        body="\n".join(f"#{i}= {s};" for i,s in self.e)
        head="""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('CENTERLINES IFC4'),'2;1');
FILE_NAME('building.ifc','20.08.2026T00:00:00',(' '),(' '),'CENTERLINES','Windows',' ');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
"""
        Path(path).write_text(head+body+"\nENDSEC;\nEND-ISO-10303-21;\n",encoding="utf-8")
