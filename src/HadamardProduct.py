"""
This file contains the PyTorch implementation of a simple Hadamard Product layer.

References:
  - https://discuss.pytorch.org/t/passing-hidden-layers-to-convlstm/52814/3
"""

import torch

from torch import nn


class HadamardProduct(nn.Module):
    """A Hadamard product layer.
    
    Args:
        shape: The shape of the layer."""
       
    def __init__(self, shape):
        super().__init__()
        self.weights = nn.Parameter(torch.empty(*shape))
        self.bias = nn.Parameter(torch.empty(*shape))
           
    def forward(self, x):
        return x * self.weights + self.bias
