import numpy as np
from hanan.optimization.optimizer import Optimizer

num_vec = 10

opt = Optimizer()

opt.add_variable("test_var", num_vec*3)

opt.initialize_optimizer("LM", 0.8, verbose=True)

# Create 10 random 3D points
points = np.random.rand(num_vec, 3)*50

opt.init_variable("test_var", points.flatten()) 

opt.unitize_variable("test_var", 3, w=10.0)
opt.control_variable("test_var", w=0.001)

# Run 10 steps
for i in range(2000):
    opt.get_gradients()
    opt.optimize_step()

opt.print_energy_report()

print("Final variable values:")
print(np.linalg.norm(opt.X.reshape(-1, 3), axis=1))  # Should be close to 1

