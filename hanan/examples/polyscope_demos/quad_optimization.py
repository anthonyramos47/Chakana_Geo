import numpy as np
import polyscope as ps
import polyscope.imgui as psim
from hanan.geometry.mesh import Mesh
from hanan import glyphs
from hanan.geometry.utils import (
    read_obj, normalize_vertices, planarity_measure_quad_mesh,
    circle_3pts,
    compute_circumcircles_quad_mesh,
    write_obj

)   

from hanan.optimization.optimizer import Optimizer
from hanan.optimization.planarity import Planarity
from hanan.optimization.cyclicity import Cyclicity
import os


data_path = os.path.join(os.path.dirname(__file__), "data/")
name = "cone_mesh_0.obj"
#name = "tri_mesh.obj"
#name = "seashell.obj"



vertices, faces = read_obj(data_path+name)

vertices = normalize_vertices(vertices)
vertices += np.random.rand(*vertices.shape) * 0.001

mesh = Mesh()
mesh.make_mesh(vertices, faces)

face_normals = mesh.face_normals
vertex_normals = mesh.vertex_normals
corners = mesh.corners()
corner_adjlst = [mesh.vertex_adjacency_list()[i] for i in corners]
face_barycenters = mesh.face_barycenters()
inner_vertices = mesh.inner_vertices()
vertex_face_adjacency_list = mesh.vertex_face_adjacency_list()
inner_vertex_face_adjacency_list = [vertex_face_adjacency_list[i] for i in inner_vertices]

# --- Optimizer setup ---
# Step 1: declare variable blocks and set initial values
optimizer = Optimizer()
optimizer.add_variable("v",     vertices.flatten())
optimizer.add_variable("n_f",   face_normals.flatten())
optimizer.add_variable("cf",    face_barycenters.flatten())                   # auxiliary variable for circumcenter in circularity term
optimizer.add_variable("aux_n", vertex_normals[inner_vertices].flatten())     # auxiliary normals at inner vertices

# Step 2: register energy terms (uses current X for Jacobian structure)
planarity = Planarity()
optimizer.add_objective_term(planarity, args=([faces]), w=1, ce=True)

vertex_adjacency_list = mesh.vertex_adjacency_list()
face_adjacency_list = mesh.face_face_adjacency_list()
four_valent_vertices = [i for i, adj in enumerate(vertex_adjacency_list) if len(adj) == 4]
four_valent_adjacency_list = [adj for adj in vertex_adjacency_list if len(adj) == 4]

cyclicity_term = Cyclicity()
optimizer.add_objective_term(cyclicity_term, args=(faces, "v", "cf", "n_f"), w=1, ce=True)


# # Conical mesh obtained by planarity of normals in Gauss map
# conical_term = Planarity() 
# conical_term.name = "Conical" # Name of the constraint
# optimizer.add_objective_term(conical_term, args=(inner_vertex_face_adjacency_list, "n_f", "aux_n"), w=1, ce=True)



# quad_fairness = QuadFairness()
# optimizer.add_objective_term(quad_fairness, args=("v", four_valent_vertices, four_valent_adjacency_list, 3, 0.9, 10), w=0.01, ce=True)


# optimizer.set_lap_smooth("v", np.arange(len(mesh.vertices)) , vertex_adjacency_list, dim=3, damp_factor=0.9, damp_iteration=10, w=0.001, ce=True)

optimizer.set_fairness("v", mesh.vertex_adjacency_list(), dim=3, damp_factor=0.8, damp_iteration=20, w=0.001, ce=True)
optimizer.set_fairness("n_f", face_adjacency_list, dim=3, damp_factor=0.8, damp_iteration=20, w=0.003, ce=True)

edges = mesh.edge_vertices()
optimizer.edge_length("v", edges, target_length=None, w=1)
optimizer.unitize_variable("n_f", 3,  w=5)
optimizer.unitize_variable("aux_n", 3,  w=5)


# Step 3: reset iteration bookkeeping, then run
optimizer.initialize_optimizer(verbose=True, adaptive_mu=False)



def loop(variables):


    psim.Text("Running optimization...")


    if psim.Button("Run optimization step"):
        variables["run"] = True

        
    if variables["it"] > variables["max_iterations"]:
        psim.Text("Optimization complete.")
        optimizer.print_report()
        new_vertices = optimizer.unpack("v").reshape(-1, 3)
        circum_centers = optimizer.unpack("cf").reshape(-1, 3)
        normals  = optimizer.unpack("n_f").reshape(-1, 3)
        faces = variables["mesh"].faces

        centers, normals, radius = compute_circumcircles_quad_mesh(new_vertices, faces)
        ps.register_curve_network("Circles_Quad_Mesh", *glyphs.circles(centers, normals, radius),
                                  color=(1, 0, 0), radius=0.001)
        
        variables["run"] = False  # stop further optimization steps
        variables["it"] = 0  # reset iteration count for potential future runs

    if variables["run"]:
        variables["it"] += 1
        optimizer.get_gradients()
        optimizer.optimize_step()
        new_vertices = optimizer.unpack("v").reshape(-1, 3)
        mesh.vertices = new_vertices
        mesh.update_mesh()
        faces = variables["mesh"].faces
        optimized_mesh = ps.register_surface_mesh("Optimized mesh", new_vertices, faces)

        gv, gf, ge = mesh.gauss_image()

        gv += [0, 0, 2]

        ps.register_curve_network("Gauss image Opt", gv, ge)

        write_obj(data_path+name.split('.')[0]+"_optimized.obj", mesh.vertices, mesh.faces)
        #planarity_values = planarity_measure_quad_mesh(variables["mesh"])
        
        #optimized_mesh.add_scalar_quantity("Planarity", planarity_values, defined_on="faces")



variables = {"optimizer": optimizer,
             "mesh": mesh,
             "max_iterations": 20,
             "it": 0,
             "run": False
            }



ps.init()
ps.remove_all_structures()

ps.register_surface_mesh("mesh", vertices, faces)


gv, gf, ge = mesh.gauss_image()

gv += [0, 0, -1]

ps.register_curve_network("Gauss image", gv, ge)


ps.set_user_callback(lambda: loop (variables))  # No-op callback to keep the UI responsive during optimization
ps.show()