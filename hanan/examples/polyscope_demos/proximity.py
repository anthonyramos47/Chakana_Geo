import numpy as np
import polyscope as ps
import polyscope.imgui as psim
from hanan.optimization.optimizer import Optimizer
from hanan.geometry.utils import read_obj, make_param_grid_vec
from hanan.geometry.mesh import Mesh
import time

# Import mesh
#V, F = read_obj("data/meshFairnesTest.obj")
#V, F = read_obj("data/bunny.obj")

# Create a square grid n x m unit squares in the XY plane
uv, facesRef = make_param_grid_vec((-1, 1), (-1, 1), 150, 150)
verticesRef = np.array( [ [u, u**2+v**2, v] for u,v in uv ] )

uv, faces = make_param_grid_vec((-1, 1), (-1, 1), 20, 20)
vertices = np.array( [ [u-0.5, u**2-v**2 - 0.2, v + 0.02] for u,v in uv ] )


mesh= Mesh()
mesh.make_mesh(vertices, faces)

v_v_adj = mesh.vertex_adjacency_list()
edges = mesh.edge_vertices()

# # Initialize optimizer
opt = Optimizer()

# # Add vertex variable
num_vertices = vertices.shape[0]
opt.add_variable("v", num_vertices * 3)

# # Initialize optimizer
opt.initialize_optimizer("LM", 1.0, verbose=True)

# Initialize vertex variable
opt.init_variable("v", vertices.flatten())

# Add Laplacian fairness constraint
opt.set_lap_smooth("v", v_v_adj, 3, 0.1)

opt.proximity_reference("v", verticesRef, facesRef, w_proximity=0.002, w_gliding=0.2)

# opt.unitize_variable("v", 3, w=10.0)
opt.control_variable("v", w=0.5)

#opt.fix_values_variables("v", indices=np.array([4,5,6,12,13,14]), fixed_values=np.array([-1,-1,-1, -1, -1, 1]), w=1.0)
opt.edge_length("v", edges, target_length=None, w=0.5)

# # Optimize
# for i in range(200):
#     opt.get_gradients()
#     opt.optimize_step()

# opt.print_energy_report()

# V_new = opt.unpack("v").reshape(-1, 3) 

it = 0
activate=False

def vis_opt():
    global it, activate
    """
    Visualize the original and optimized meshes using Polyscope.
    """

    if psim.Button("Run Optimization"):
        it = 0 
        activate=True

    if activate and it < 20:
        opt.get_gradients()
        opt.optimize_step()
        V_new = opt.unpack("v").reshape(-1, 3) 
        ps.register_surface_mesh("Opt Surface", V_new, faces)
        it += 1

    if it == 20:
        activate=False

    if psim.Button("Print Report"):
        pass
        #opt.print_energy_report()


# Initialize polyscope
ps.init()
ps_mesh  = ps.register_surface_mesh("Reference Surface", verticesRef, facesRef)
ps_mesh2 = ps.register_surface_mesh("Opt Surface", vertices, faces)

ps.set_user_callback(vis_opt)

ps.show()



