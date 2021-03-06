"""
This file contains the implementation of the environment from the point of view of a single agent. The environment class SingleRLAgent embeds three subclasses (FingerLayer, ExternalRepresentation, OtherInteractions) which implement the dynamics of the different environment parts.
"""
import time
from PIL import Image, ImageDraw
from IPython.display import display, update_display
import numpy as np
import utils
import random

# TODO (?): later in utils
from PIL import ImageFont
#from fonts.ttf import AmaticSC

class SingleRLAgent():
    """
    This class implements the environment as a whole.
    """
    def __init__(self, agent_params):
        model=None
        self.max_objects = agent_params['max_objects']
        self.n_objects = random.randint(1, self.max_objects)
        self.obs_dim = agent_params['obs_dim']
        
        # Initialize observation: 1-max_objects randomly placed 1s placed on a 0-grid of shape dim x dim
        self.obs = np.zeros((self.obs_dim, self.obs_dim))
        self.obs.ravel()[np.random.choice(self.obs.size, self.n_objects, replace=False)] = 1

        # Initialize external representation (the piece of paper the agent is writing on)
        self.ext_repr = ExternalRepresentation(self.obs_dim)
        
        # Initialize Finger layer: Single 1 in 0-grid of shape dim x dim
        self.fingerlayer = FingerLayer(self.obs_dim)
        
        # Initialize whole state space: concatenated observation and external representation
        self.state = np.stack([self.obs, self.fingerlayer.fingerlayer, self.ext_repr.externalrepresentation])
        
        # Initialize other interactions: e.g. 'submit', 'larger'/'smaller,
        self.otherinteractions = OtherInteractions()
        
        # Initialize action
        self.all_actions_list, self.all_actions_dict = self.merge_actions([self.ext_repr.actions, self.fingerlayer.actions, self.otherinteractions.actions])
        self.all_actions_dict_inv = dict([reversed(i) for i in self.all_actions_dict.items()])
        int_to_int = {}
        for key, value in self.all_actions_dict_inv.items():
            int_to_int[value] = value
        self.all_actions_dict_inv.update(int_to_int)
        
        # Rewrite keys of individual action-spaces, so they do not overlap in the global action space
        self.ext_repr.actions = self.rewrite_action_keys(self.ext_repr.actions)
        self.fingerlayer.actions = self.rewrite_action_keys(self.fingerlayer.actions)

        self.action_dim = len(self.all_actions_list)
        self.action = np.zeros(self.action_dim)

        # Initialize neural network model: maps observation-->action
        self.model = model
        self.fps_inv = 500 #ms
        self.is_submitted_ext_repr = False
        self.submitted_ext_repr = None

    def step(self, action):
        # Define how actiocn interacts with environment: e.g. with observation space and external representation
        # self.obs.step(action_on_obs[action]) # no interaction with the observation space yet

        if(action in self.fingerlayer.actions):
            self.fingerlayer.step(action)

        # For action on external representation:
        # Give as argument: either pixel-positions (1D or 2D) to draw on.
        #                   or draw_point/not-draw at the current finger-position
        if(action in self.ext_repr.actions):
            self.ext_repr.draw_point([self.fingerlayer.pos_x, self.fingerlayer.pos_y])

        if(action in self.otherinteractions.actions):
            if (action == 'submit'):
                self.is_submitted_ext_repr = True
                self.submitted_ext_repr = self.ext_repr.externalrepresentation
            elif (action == 'larger'):
                pass
            elif (action == 'smaller'):
                pass

        # Build action-array according to the int/string action. This is mainly for the demo mode, where actions are given
        # manually by str/int. When trained action-array is input.
        self.action = np.zeros(self.action_dim)
        self.action[self.all_actions_dict_inv[action]] = 1


    def select_action(self, state):
        # Interface with Flavio's pytorch-agent:
        # output = convlstm_model(self.state)
        # action = set to discrete actions of output
        eps = IsTest or self.eps

        # model_output = self.model(state)
        if random.random() <= ep:
            action_index = random.randrange(Actions)
        else:
            action = torch.argmax(self.critic.q_t_values(observation), dim=1).cpu().numpy()
        return action

    def render(self, display_id=None):
        img_height=200
        self.obs_img = Image.fromarray(self.obs*255).resize( (img_height,img_height), resample=0)
        self.obs_img = utils.add_grid_lines(self.obs_img, self.obs)
        self.obs_img = self.obs_img.transpose(Image.TRANSPOSE)
        self.obs_img = utils.annotate_below(self.obs_img, "Observation")

        self.action_img = Image.fromarray(self.action*255).resize( (int(img_height/4),img_height), resample=0)
        self.action_img = utils.add_grid_lines(self.action_img, np.reshape(self.action, (-1, 1)))
        self.action_img = utils.annotate_nodes(self.action_img, self.all_actions_list)
        self.action_img = utils.annotate_below(self.action_img, "Action")


        self.ext_repr_img = Image.fromarray(self.ext_repr.externalrepresentation*255).resize( (img_height,img_height), resample=0)
        self.ext_repr_img = utils.add_grid_lines(self.ext_repr_img, self.ext_repr.externalrepresentation)
        self.ext_repr_img = self.ext_repr_img.transpose(Image.TRANSPOSE)
        self.ext_repr_img = utils.annotate_below(self.ext_repr_img, "External representation")

        self.finger_img = Image.fromarray(self.fingerlayer.fingerlayer*255).resize( (img_height,img_height), resample=0)
        self.finger_img = utils.add_grid_lines(self.finger_img, self.fingerlayer.fingerlayer)
        self.finger_img = self.finger_img.transpose(Image.TRANSPOSE)
        self.finger_img = utils.annotate_below(self.finger_img, "Finger layer")
        total_img = utils.concat_imgs_h([self.obs_img, self.finger_img, self.ext_repr_img, self.action_img], dist=10).convert('RGB')
        if(display_id is not None):
            display(total_img, display_id=display_id)
            time.sleep(self.fps_inv)
        return total_img

    def reset(self):
        self.obs = np.zeros((self.dim, self.dim))
        self.obs.ravel()[np.random.choice(obs.size, self.max_objects, replace=False)] = 1
        self.ext_repr = np.zeros((self.dim, self.dim))
        self.fingerlayer = FingerLayer(self.obs_dim)

    def merge_actions(self, action_dicts):
        """This function creates the actions dict for the complete environment merging the ones related to the individual environment parts.
        """
        self.all_actions_list = []
        self.all_actions_dict = {}
        _n = 0
        for _dict in action_dicts:
            rewritten_individual_dict = {}
            for key,value in _dict.items():
                if(isinstance(value, str) and value not in self.all_actions_list):
                    self.all_actions_list.append(value)
                    self.all_actions_dict[_n] = value
                    rewritten_individual_dict[_n] = value
                    _n += 1
            _dict = rewritten_individual_dict
        #self.all_actions_dict = sorted(self.all_actions_dict.items())
        self.all_actions_list = [value for key, value in self.all_actions_dict.items()]
        return self.all_actions_list, self.all_actions_dict

    def rewrite_action_keys(self, _dict):
        """Function used to rewrite keys of individual action-spaces, so they do not overlap in the global action space.
        """
        rewritten_dict = {}
        for key, value in _dict.items():
            if(isinstance(key, int)):
                rewritten_dict[self.all_actions_dict_inv[value]] = value
        str_to_str = {}
        for key,value in rewritten_dict.items():
            str_to_str[value] = value
        rewritten_dict.update(str_to_str)
        return rewritten_dict

class FingerLayer():
    """
    This class implements the finger movement part of the environment.
    """
    def __init__(self, dim):
        self.dim = dim
        self.fingerlayer = np.zeros((dim, dim))
        self.max_x = dim-1
        self.max_y = dim-1
        self.pos_x = random.randint(0, dim-1)
        self.pos_y = random.randint(0, dim-1)
        self.fingerlayer[self.pos_x, self.pos_y] = 1
        # This dictionary translates the total action-array to the Finger-action-strings:
        # Key will be overwritten when merged with another action-space
        self.actions = {
            0: 'left',
            1: 'right',
            2: 'up',
            3: 'down'
        }
        # revd=dict([reversed(i) for i in finger_movement.items()])
        # Add each value as key as well. so in the end both integers (original keys) and strings (original values) can be input
        str_to_str = {}
        for key, value in self.actions.items():
            str_to_str[value] = value
        self.actions.update(str_to_str)

    def step(self, move_action):
        move_action_str = self.actions[move_action]
        if(move_action_str=="right"):
            if(self.pos_x<self.max_x):
                self.pos_x += 1
        elif(move_action_str=="left"):
            if(self.pos_x > 0):
                self.pos_x -= 1
        elif(move_action_str=="up"):
            if(self.pos_y > 0):
                self.pos_y -= 1
        elif(move_action_str=="down"):
            if (self.pos_y < self.max_y):
                self.pos_y += 1
        self.fingerlayer = np.zeros((self.dim, self.dim))
        self.fingerlayer[self.pos_x, self.pos_y] = 1


class ExternalRepresentation():
    """
    This class implements the external representation in the environment.
    """
    def __init__(self, dim):
        self.dim = dim
        self.externalrepresentation = np.zeros((dim, dim))
        self.actions = {
            0: 'mod_point',      # Keys will be overwritten when merged with another action-space
        }
        str_to_str = {}
        for key,value in self.actions.items():
            str_to_str[value] = value
        self.actions.update(str_to_str)

    def draw(self, draw_pixels):
        self.externalrepresentation += draw_pixels

    def draw_point(self, pos):
        # This line implements if ext_repr[at_curr_pos]==0 --> set it to 1. if==1 set to 0.
        self.externalrepresentation[pos[0], pos[1]] = -self.externalrepresentation[pos[0], pos[1]] + 1


class OtherInteractions():
    """
    This class implements the environmental responses to actions related to communication with the other agent ('submit') or to the communication of the final answer ('larger', 'smaller').
    """
    def __init__(self):
        self.actions = {
            0: 'submit',  # Keys will be overwritten when merged with another action-space
            1: 'larger',
            2: 'smaller'
        }
        # Add each value as key as well. so in the end both integers (original keys) and strings (original values) can be input
        str_to_str = {}
        for key, value in self.actions.items():
            str_to_str[value] = value
        self.actions.update(str_to_str)






if __name__ == '__main__':
    agent_params = {
        'max_objects': 9,
        'obs_dim': 4,
    }


    agent = SingleRLAgent(agent_params)
    agent.render()
    action = 'mod_point'
    agent.step(action)
