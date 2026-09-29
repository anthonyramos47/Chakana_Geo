import numpy as np
import polyscope as ps
import polyscope.imgui as psim
from hanan.optimization.optimizer import Optimizer
from hanan.geometry.utils import read_obj
from hanan.geometry.mesh import Mesh
import time

# Import mesh
#V, F = read_obj("data/meshFairnesTest.obj")
#V, F = read_obj("data/bunny.obj")
V, F = read_obj("data/small_mesh.obj")

mesh = Mesh()
mesh.make_mesh(V, F)

v_v_adj = mesh.vertex_adjacency_list()
edges = mesh.edge_vertices()



# Initialize optimizer
opt = Optimizer()

# Add vertex variable
num_vertices = V.shape[0]
opt.add_variable("v", num_vertices * 3)

# Initialize optimizer
opt.initialize_optimizer("LM", 1.0, verbose=True)

# Initialize vertex variable
opt.init_variable("v", V.flatten())

# Add Laplacian fairness constraint
opt.set_fairness("v", v_v_adj, 3, 0.01)
opt.unitize_variable("v", 3, w=10.0)
opt.control_variable("v", w=0.5)
opt.edge_length("v", edges, target_length=None, w=0.1)

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
        ps.register_surface_mesh("Optimized Mesh", V_new, F)
        it += 1

    if it == 20:
        activate=False

    if psim.Button("Print Report"):
        opt.print_energy_report()


# Initialize polyscope
ps.init()
ps_mesh  = ps.register_surface_mesh("Fairness Test Mesh", V, F)

ps.set_user_callback(vis_opt)

ps.show()



